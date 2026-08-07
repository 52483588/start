import json
import sys
from playwright.sync_api import sync_playwright

def main():
    api_response = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)   # 云端无头模式
        page = browser.new_page()

        def handle_response(response):
            nonlocal api_response
            if "/infoApi/sc/D/FB/matchs/results" in response.url:
                try:
                    data = response.json()
                    if data:
                        api_response = data
                        print("✅ 成功拦截到 results API 数据！")
                except Exception as e:
                    print(f"⚠️ 解析 API 响应失败: {e}")

        page.on("response", handle_response)

        print("🔄 正在加载历史赛果页面，等待数据...")
        page.goto("https://www.macauslot.com/sc/soccer/matchResult.html", wait_until="networkidle")
        
        for _ in range(40):
            if api_response:
                break
            page.wait_for_timeout(500)
        else:
            print("❌ 未能在 20 秒内捕获到 API 响应")
            browser.close()
            sys.exit(1)

        browser.close()

    if api_response:
        with open('results.json', 'w', encoding='utf-8') as f:
            json.dump(api_response, f, indent=2, ensure_ascii=False)
        print("✅ 历史赛果数据已保存到 results.json")
    else:
        print("❌ 未获取到任何数据")
        sys.exit(1)

if __name__ == "__main__":
    main()