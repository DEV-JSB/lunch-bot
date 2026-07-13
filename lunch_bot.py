import os
import re
import sys
import json
import hashlib
import urllib.request

CHANNEL_URL = "https://pf.kakao.com/_mYxfen"
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
STATE_FILE = os.environ.get("STATE_FILE", ".last_menu")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def fetch_profile_image() -> str:
    html = get(CHANNEL_URL).decode("utf-8", "replace")
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    if not m:
        sys.exit("og:image 를 못 찾았습니다. 페이지 구조가 바뀐 듯.")

    url = m.group(1).replace("http://", "https://")

    # img_m.jpg -> 더 큰 사이즈가 있으면 그걸 사용
    for size in ("img_l.jpg", "img_640x640.jpg"):
        cand = re.sub(r"img_[^/]+$", size, url)
        try:
            req = urllib.request.Request(cand, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return cand
        except Exception:
            continue
    return url


def already_posted(url: str) -> bool:
    key = hashlib.sha1(url.encode()).hexdigest()
    prev = None
    if os.path.exists(STATE_FILE):
        prev = open(STATE_FILE).read().strip()
    if prev == key:
        return True
    with open(STATE_FILE, "w") as f:
        f.write(key)
    return False


def post_to_slack(image_url: str) -> None:
    payload = {
        "text": "오늘의 구내식당 메뉴 🍚",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🍚 오늘의 구내식당 메뉴", "emoji": True},
            },
            {
                "type": "image",
                "image_url": image_url,
                "alt_text": "구내식당 메뉴판",
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"<{CHANNEL_URL}|밥(온) 구내식당 채널> · 1인 7,500원"}
                ],
            },
        ],
    }
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status != 200:
            sys.exit(f"Slack 전송 실패: {r.status}")


if __name__ == "__main__":
    img = fetch_profile_image()
    force = "--force" in sys.argv
    if not force and already_posted(img):
        print("프로필 사진이 그대로임 (아직 메뉴 갱신 안 됨). 스킵.")
        sys.exit(0)
    post_to_slack(img)
    print(f"전송 완료: {img}")
