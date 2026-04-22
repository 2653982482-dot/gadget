import json
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _parse_iso_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_post_text(raw_text: str, username: str, time_label: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return ""

    if time_label in lines:
        lines = lines[lines.index(time_label) + 1 :]

    skip_words = {
        "Follow",
        "Mention",
        "Threads",
        "Replies",
        "Media",
        "Reposts",
        "Pinned",
        "Like",
        "Comment",
        "Repost",
        "Share",
        "Send",
        "More",
    }

    cleaned_lines = []
    for line in lines:
        if line.lower() == username.lower():
            continue
        if line in skip_words:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if line.startswith("http"):
            continue
        if not cleaned_lines or cleaned_lines[-1] != line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _extract_raw_posts(page):
    return page.evaluate(
        """() => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
            const seen = new Set();
            const posts = [];

            for (const anchor of anchors) {
                const href = anchor.getAttribute('href') || '';
                if (href.includes('/media')) {
                    continue;
                }

                const timeEl = anchor.querySelector('time');
                if (!timeEl) {
                    continue;
                }

                const postUrl = new URL(href, window.location.origin).toString();
                if (seen.has(postUrl)) {
                    continue;
                }
                seen.add(postUrl);

                let container = anchor;
                let bestText = (anchor.innerText || '').trim();
                for (let i = 0; i < 12 && container; i += 1) {
                    const text = (container.innerText || '').trim();
                    if (text.length > bestText.length) {
                        bestText = text;
                    }
                    if (text.split('\\n').length >= 5 || text.length >= 80) {
                        bestText = text;
                        break;
                    }
                    container = container.parentElement;
                }

                posts.push({
                    url: postUrl,
                    time_ago: (timeEl.innerText || '').trim(),
                    datetime: timeEl.getAttribute('datetime') || '',
                    raw_text: bestText,
                });
            }

            return posts;
        }"""
    )


def scrape_threads_24h(username: str):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 2400})

        try:
            page.goto(
                f"https://www.threads.net/@{username}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_selector('a[href*="/post/"]', timeout=15000)
        except PlaywrightTimeoutError:
            browser.close()
            return []

        page.wait_for_timeout(3000)

        for _ in range(5):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1500)

        raw_posts = _extract_raw_posts(page)
        browser.close()

    results = []
    seen_urls = set()
    for post in raw_posts:
        post_time = _parse_iso_datetime(post.get("datetime", ""))
        if not post_time or post_time < cutoff:
            continue

        post_url = post["url"]
        if post_url in seen_urls:
            continue
        seen_urls.add(post_url)

        text = _clean_post_text(
            raw_text=post.get("raw_text", ""),
            username=username,
            time_label=post.get("time_ago", ""),
        )
        if len(text) < 10:
            continue

        results.append(
            {
                "time_ago": post["time_ago"],
                "datetime": post["datetime"],
                "url": post_url,
                "text": text,
            }
        )

    return results

if __name__ == "__main__":
    # 执行抓取任务 (mattnavarra 过去 24 小时推文)
    results = scrape_threads_24h("mattnavarra")
    
    # 直接输出纯净的 JSON 原文字符串
    print(json.dumps(results, ensure_ascii=False, indent=2))
