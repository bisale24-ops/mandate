"""Record the demo clips from the running page (local server, live PayPal sandbox).

    PORT=8795 ~/.venvs/video/bin/python video/record.py      # writes video/clips/*.webm
"""
import os
import pathlib
import shutil

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
OUT = HERE / "clips"
URL = f"http://127.0.0.1:{os.environ.get('PORT', '8795')}/"


def glide(page, to_selector, steps=40, pause=18):
    y0 = page.evaluate("window.scrollY")
    y1 = page.evaluate(f"document.querySelector('{to_selector}').getBoundingClientRect().top + window.scrollY - 70")
    for i in range(1, steps + 1):
        page.evaluate(f"window.scrollTo(0, {y0 + (y1 - y0) * i / steps})")
        page.wait_for_timeout(pause)


def clip(browser, name, act):
    tmp = OUT / f"_{name}"
    shutil.rmtree(tmp, ignore_errors=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                              record_video_size={"width": 1280, "height": 720}, color_scheme="light")
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(800)
    act(page)
    video = page.video
    ctx.close()
    pathlib.Path(video.path()).replace(OUT / f"{name}.webm")
    shutil.rmtree(tmp, ignore_errors=True)
    print(name, flush=True)


def hero(page):
    page.wait_for_timeout(6000)


def attack(product, kind):
    def act(page):
        glide(page, "#demo", steps=30)
        page.select_option("#product", product)
        page.wait_for_timeout(500)
        page.select_option("#attack", kind)
        page.wait_for_timeout(700)
        page.click("#run")
        page.wait_for_selector("#right .receipt", timeout=180000)
        page.wait_for_timeout(1200)
        glide(page, "#inj", steps=20)
        page.wait_for_timeout(2500)
        glide(page, "#right .receipt", steps=40)
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollBy({top: 420, behavior: 'smooth'})")
        page.wait_for_timeout(4000)
    return act


def bench(page):
    glide(page, "#bench", steps=50)
    page.wait_for_timeout(8000)


def toolkit(page):
    glide(page, "#toolkit", steps=60)
    page.wait_for_timeout(7000)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        clip(browser, "hero", hero)
        clip(browser, "fee", attack("tent", "fee"))
        clip(browser, "upsell", attack("headphones", "upsell"))
        clip(browser, "bench", bench)
        clip(browser, "toolkit", toolkit)
        browser.close()


if __name__ == "__main__":
    main()
