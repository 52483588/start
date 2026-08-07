import json
import sys
from playwright.sync_api import sync_playwright

def main():
    api_response = None

    with sync_playwright() as p:
        # 启动浏览器（云端用 headless=True，本地调试可改为 False）
        # 若本地需要走代理，请取消注释下面的 proxy 并填写你的代理端口
        browser = p.chromium.launch(
            headless=True,
            # proxy={"server": "http://127.0.0.1:7897"}   # 本地有代理时放开
        )
        page = browser.new_page()

        def handle_response(response):
            nonlocal api_response
            # 拦截目标 API（实时比分）
            if "/infoApi/sc/D/FB/matchs/livescore" in response.url:
                try:
                    data = response.json()
                    if data:
                        api_response = data
                        print("✅ 成功拦截到 livescore API 数据！")
                except Exception as e:
                    print(f"⚠️ 解析 API 响应失败: {e}")

        page.on("response", handle_response)

        # 访问实时比分页面
        print("🔄 正在加载实时比分页面，等待数据...")
        page.goto("https://www.macauslot.com/sc/soccer/livescore.html", wait_until="networkidle")
        
        # 最多等待 20 秒捕获响应
        for _ in range(40):
            if api_response:
                break
            page.wait_for_timeout(500)
        else:
            print("❌ 未能在 20 秒内捕获到 API 响应，可能页面结构已变化。")
            browser.close()
            sys.exit(1)

        browser.close()

    if api_response:
        with open('scores.json', 'w', encoding='utf-8') as f:
            json.dump(api_response, f, indent=2, ensure_ascii=False)
        print("✅ 实时比分数据已保存到 scores.json")
    else:
        print("❌ 未获取到任何数据")
        sys.exit(1)

if __name__ == "__main__":
    main()