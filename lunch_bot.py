import os
import re
import sys
import json
import hashlib
import urllib.request
import urllib.error

CHANNEL_URL = "https://pf.kakao.com/_mYxfen"
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "")
STATE_FILE = os.environ.get("STATE_FILE", ".last_menu")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def http(url, data=None, headers=None, method=None, timeout=20):
    """요청 후 (status, body_bytes) 반환. 4xx/5xx 도 예외 대신 그대로 돌려줌."""
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": UA, **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---------- 1. 카카오 채널에서 프로필 이미지 URL 뽑기 ----------

def fetch_profile_image():
    status, body = http(CHANNEL_URL)
    if status != 200:
        sys.exit(f"[FAIL] 카카오 채널 응답 {status}")

    html = body.decode("utf-8", "replace")
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
    if not m:
        sys.exit("[FAIL] og:image 태그를 못 찾음. 페이지 구조가 바뀐 듯.")

    url = m.group(1).replace("http://", "https://")
    print(f"[OK] og:image = {url}")

    # 더 큰 해상도가 있으면 그걸로 교체
    for size in ("img_l.jpg", "img_640x640.jpg"):
        cand = re.sub(r"img_[^/]+$", size, url)
        status, _ = http(cand, method="HEAD", timeout=10)
        if status == 200:
            print(f"[OK] 더 큰 버전 사용: {cand}")
            return cand

    return url


# ---------- 2. 중복 전송 방지 ----------

def already_posted(url):
    key = hashlib.sha1(url.encode()).hexdigest()
    prev = open(STATE_FILE).read().strip() if os.path.exists(STATE_FILE) else None
    with open(STATE_FILE, "w") as f:
        f.write(key)
    return prev == key


# ---------- 3-A. Webhook 으로 전송 (이미지 블록) ----------

def post_via_webhook(image_url):
    payload = {
        "text": "오늘의 구내식당 메뉴 🍚",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🍚 오늘의 구내식당 메뉴", "emoji": True}},
            {"type": "image", "image_url": image_url, "alt_text": "구내식당 메뉴판"},
            {"type": "context",
             "elements": [{"type": "mrkdwn",
                           "text": f"<{CHANNEL_URL}|밥(온) 구내식당> · 1인 7,500원"}]},
        ],
    }
    status, body = http(
        SLACK_WEBHOOK,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    text = body.decode("utf-8", "replace")
    print(f"[Slack webhook] {status} {text}")
    return status == 200


# ---------- 3-B. Bot Token 으로 이미지 직접 업로드 ----------

def post_via_upload(image_url):
    """카카오 CDN 이 핫링킹을 막을 때 쓰는 경로. SLACK_BOT_TOKEN 필요."""
    status, img = http(image_url)
    if status != 200:
        sys.exit(f"[FAIL] 이미지 다운로드 실패 {status}")
    print(f"[OK] 이미지 {len(img):,} bytes 다운로드")

    auth = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

    # (1) 업로드 URL 발급
    status, body = http(
        "https://slack.com/api/files.getUploadURLExternal",
        data=urllib.parse.urlencode(
            {"filename": "menu.jpg", "length": str(len(img))}
        ).encode(),
        headers={**auth, "Content-Type": "application/x-www-form-urlencoded"},
    )
    res = json.loads(body)
    if not res.get("ok"):
        sys.exit(f"[FAIL] getUploadURLExternal: {res}")
    upload_url, file_id = res["upload_url"], res["file_id"]

    # (2) 바이트 업로드
    status, _ = http(upload_url, data=img, method="POST")
    if status != 200:
        sys.exit(f"[FAIL] 업로드 {status}")

    # (3) 채널에 게시
    status, body = http(
        "https://slack.com/api/files.completeUploadExternal",
        data=json.dumps({
            "files": [{"id": file_id, "title": "오늘의 구내식당 메뉴"}],
            "channel_id": SLACK_CHANNEL,
            "initial_comment": f"🍚 *오늘의 구내식당 메뉴*\n<{CHANNEL_URL}|밥(온) 구내식당> · 1인 7,500원",
        }).encode(),
        headers={**auth, "Content-Type": "application/json; charset=utf-8"},
    )
    res = json.loads(body)
    print(f"[Slack upload] {res}")
    if not res.get("ok"):
        sys.exit(f"[FAIL] completeUploadExternal: {res}")
    return True


# ---------- main ----------

if __name__ == "__main__":
    import urllib.parse  # post_via_upload 에서 사용

    force = "--force" in sys.argv
    img = fetch_profile_image()

    if already_posted(img) and not force:
        print("[SKIP] 프로필 사진 그대로. 아직 메뉴 갱신 안 됨.")
        sys.exit(0)

    if SLACK_BOT_TOKEN and SLACK_CHANNEL:
        print("[MODE] Bot token 업로드")
        post_via_upload(img)
    elif SLACK_WEBHOOK:
        print("[MODE] Webhook")
        if not post_via_webhook(img):
            sys.exit("[FAIL] Webhook 거부됨. 위 응답 본문 확인.")
    else:
        sys.exit("[FAIL] SLACK_WEBHOOK_URL 또는 SLACK_BOT_TOKEN+SLACK_CHANNEL 필요.")

    print("[DONE]")