from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, os, requests, json, platform
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone


# --------- 변수 설정 ---------
DEBUG = False

CHANNEL_URL = "https://arca.live/b/cook"  # 크롤링할 아카라이브 채널 URL
EMPTY_PAGE_LIMIT = 100  # 해당 페이지동안 크롤링 가능한 글이 나오지 않을 경우 종료
SAVE_DIR = "articles"
CSS_DIR = os.path.join(SAVE_DIR, "css")
PROGRESS_FILE = "progress.json"
# -------------------------


current_url = None
last_saved_link = None
downloaded_css = []


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "downloaded_css" not in data:
                data["downloaded_css"] = []
            return data
    return {"last_link_number": None, "downloaded_css": []}


def save_progress(last_url, last_link_number, downloaded_css):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "last_url": last_url,
            "last_link_number": last_link_number,
            "downloaded_css": downloaded_css
        }, f)


def make_safe_filename(s):
    return "".join(c for c in s if c.isalnum() or c in " _-")[:50]


def save_article(driver, article):
    driver.get(article["link"])
    time.sleep(1)

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    # 링크에서 글 번호 추출
    link_number = article["link"].rstrip("/").split("/")[-1].split("?")[0]

    # 폴더명에 글 제목 포함
    safe_title = make_safe_filename(article["title"])
    article_dir = os.path.join(SAVE_DIR, f"{link_number}_{safe_title}")
    os.makedirs(article_dir, exist_ok=True)

    # 이미지 다운로드
    for idx, img in enumerate(soup.select("img")):
        src = img.get("src")
        if not src:
            continue
        img_url = urljoin(article["link"], src)
        try:
            res = requests.get(img_url, timeout=10)
            if res.status_code == 200:
                ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                img_filename = f"img_{idx}{ext}"
                img_path = os.path.join(article_dir, img_filename)
                with open(img_path, "wb") as f:
                    f.write(res.content)
                img["src"] = img_filename
        except:
            continue

    # CSS 다운로드 (한 번만)
    for idx, css in enumerate(soup.select("link[rel='stylesheet']")):
        href = css.get("href")
        if not href:
            continue
        css_url = urljoin(CHANNEL_URL, href)
        css_name = os.path.basename(css_url.split("?")[0])
        if css_name in downloaded_css:
            css["href"] = os.path.join("..", "css", css_name).replace("\\", "/")
            continue

        css_path = os.path.join(CSS_DIR, css_name)
        try:
            res = requests.get(css_url, timeout=10)
            if res.status_code == 200:
                with open(css_path, "w", encoding="utf-8") as f:
                    f.write(res.text)
                css["href"] = os.path.join("..", "css", css_name).replace("\\", "/")
                downloaded_css.add(css_name)
                save_progress(last_url=current_url, last_link_number=last_saved_link,
                              downloaded_css=list(downloaded_css))
        except:
            continue

    # 비디오 다운로드
    for idx, video in enumerate(soup.select("video")):
        video_src = video.get("src")
        sources = video.find_all("source")
        urls = [video_src] if video_src else []
        urls += [s.get("src") for s in sources if s.get("src")]

        for vid_idx, url in enumerate(urls):
            if not url:
                continue
            video_url = urljoin(article["link"], url)
            try:
                res = requests.get(video_url, timeout=20)
                if res.status_code == 200:
                    ext = os.path.splitext(video_url.split("?")[0])[1] or ".mp4"
                    video_filename = f"video_{idx}_{vid_idx}{ext}"
                    video_path = os.path.join(article_dir, video_filename)
                    with open(video_path, "wb") as f:
                        f.write(res.content)
                    # HTML 내 경로를 로컬 상대경로로 변경
                    if video_src:
                        video["src"] = video_filename
                    for s in sources:
                        if s.get("src") == url:
                            s["src"] = video_filename
            except:
                continue

    # HTML 저장
    html_filename = "index.html"
    html_path = os.path.join(article_dir, html_filename)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print(f"✅ Saved {html_path}")

    # 진행 상황 기록
    save_progress(last_url=current_url, last_link_number=link_number, downloaded_css=list(downloaded_css))


def parse_page(driver):
    rows = driver.find_elements(By.CSS_SELECTOR, "a.vrow.column:not(.notice)")
    articles = []

    for row in rows:
        try:
            title_elem = row.find_element(By.CSS_SELECTOR, ".vcol.col-title")
            if "(権限なし)" in title_elem.text or "(권한 없음)" in title_elem.text:
                continue

            link = row.get_attribute("href")
            articles.append({
                "link": link,
                "title": title_elem.find_element(By.CSS_SELECTOR, ".title").text.strip()
            })
        except:
            continue
    return articles


def find_next_page_url(driver):
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.page-item"))
        )
    except Exception as e:
        debug_print(f"[진단] 페이지네이션(li.page-item) 자체를 못 찾음: {repr(e)}")
        return None

    links = driver.find_elements(By.CSS_SELECTOR, "li.page-item a.page-link")
    debug_print(f"[진단] a.page-link 개수: {len(links)}")

    # --- 1단계: +1 링크 찾기 ---
    for a in links:
        try:
            text = (a.text or "").strip()
            if text == "+1":
                href = a.get_attribute("href")
                if href:
                    debug_print(f"[진단] +1 링크 발견: {href}")
                    return urljoin(CHANNEL_URL, href)
        except:
            continue

    # --- 2단계: ion-chevron-right 한 개만 포함 링크 ---
    right_candidates = []
    for i, a in enumerate(links):
        try:
            spans = a.find_elements(By.TAG_NAME, "span")
            text = (a.text or "").strip()
            span_classes = [s.get_attribute("class") or "" for s in spans]
            href = a.get_attribute("href")

            debug_print(f"[진단] 링크#{i}: text='{text}', span_class={span_classes}, href='{href}'")

            cond_single_span = (len(spans) == 1)
            cond_right_icon = any("ion-chevron-right" in sc for sc in span_classes)
            cond_no_text = (text == "")

            if cond_single_span and cond_right_icon and cond_no_text:
                right_candidates.append(a)
        except:
            continue

    if right_candidates:
        href = right_candidates[0].get_attribute("href")
        debug_print(f"[진단] ion-chevron-right 링크 발견: {href}")
        return urljoin(CHANNEL_URL, href)

    debug_print("[진단] 다음 페이지 링크를 찾지 못함.")
    return None


def main():
    edge_options = Options()
    edge_options.add_experimental_option("detach", True)
    driver_path = "msedgedriver.exe" if platform.system().lower() == "windows" else "./msedgedriver"

    service = Service(driver_path)
    driver = webdriver.Edge(service=service, options=edge_options)

    driver.get(CHANNEL_URL)
    print("⚠️ 브라우저에서 로그인 후 엔터를 눌러주세요... (QR 로그인 권장)")
    input()

    now = datetime.now(timezone.utc)
    start_url = f"{CHANNEL_URL}?before={now.strftime('%Y-%m-%dT%H%%3A%M%%3A%SZ')}"

    progress = load_progress()
    current_url = progress.get("last_url", start_url)
    last_saved_link = progress.get("last_link_number", None)
    downloaded_css = set(progress.get("downloaded_css", []))

    os.makedirs(SAVE_DIR, exist_ok=True)
    os.makedirs(CSS_DIR, exist_ok=True)

    driver.get(current_url)
    empty_count = 0

    while True:
        time.sleep(0.5)
        save_progress(last_url=current_url, last_link_number=last_saved_link, downloaded_css=list(downloaded_css))

        print(f"📖 페이지 {current_url} 크롤링 중...")
        articles = parse_page(driver)

        if not articles:
            empty_count += 1
            if empty_count >= EMPTY_PAGE_LIMIT:
                print(f"{EMPTY_PAGE_LIMIT} 페이지 연속으로 새 글 없음. 종료합니다.")
                break
        else:
            empty_count = 0
            for art in articles:
                save_article(driver, art)
                last_saved_link = art["link"].rstrip("/").split("/")[-1].split("?")[0]

        # --- 다음 페이지 버튼 찾기 (진단 메시지 포함) ---
        next_url = find_next_page_url(driver)
        if next_url:
            current_url = next_url
            driver.get(current_url)
            continue
        else:
            print("❌ 다음 페이지 버튼을 찾을 수 없어 종료합니다.")
            break

    print("🎉 모든 게시물 저장 완료")


if __name__ == "__main__":
    main()