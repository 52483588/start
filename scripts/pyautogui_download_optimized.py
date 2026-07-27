import os
import time
import subprocess
import pyperclip
import pyautogui
# 设置安全机制，鼠标移到左上角可中断脚本
pyautogui.FAILSAFE = True
# ================= 配置区域 =================
save_path = r"C:\Users\52483\Desktop\xml"
file_urls = [
    "https://www.macauslot.com/content/data/soccer/xml/odds/windrawwinfirsthalf.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/odds_config.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/windrawwin.xml",   
    "https://www.macauslot.com/content/data/soccer/xml/odds/halffull.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/winodds.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/overunder.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/numberofgoals.xml",
    "https://www.macauslot.com/content/data/soccer/xml/odds/correctscore.xml"
]
# ===========================================
def open_edge_browser(url):
    """打开 Edge 浏览器并访问指定 URL"""
    try:
        subprocess.Popen(['start', 'msedge', url], shell=True)
        time.sleep(5)  # 等待浏览器启动
        return True
    except Exception as e:
        print(f"打开浏览器失败: {e}")
        return False
def type_url_via_clipboard(url):
    """通过剪贴板输入 URL（避免字符长度限制）"""
    pyperclip.copy(url)
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'l')  # 聚焦地址栏
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'v')  # 粘贴
    time.sleep(0.5)
    pyautogui.press('enter')       # 访问
    time.sleep(3)                  # 等待页面加载
def save_file_via_keyboard(set_path=False):
    """
    模拟键盘保存文件
    :param set_path: 是否需要设置保存路径（仅第一次需要）
    """
    # Ctrl+S 打开另存为对话框
    pyautogui.hotkey('ctrl', 's')
    time.sleep(1.5)
    
    if set_path:
        # 第一次保存：设置路径
        print("  -> 正在设置保存路径...")
        pyautogui.press('f4')      # 聚焦地址栏
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'a') # 全选
        time.sleep(0.3)
        pyperclip.copy(save_path)  # 复制路径
        pyautogui.hotkey('ctrl', 'v') # 粘贴路径
        time.sleep(0.5)
        pyautogui.press('enter')   # 确认路径
        time.sleep(0.5)
        pyautogui.press('enter')   # 二次确认
        time.sleep(1.5)            # 等待路径切换生效
    
    # 确认保存 (Alt+S)
    pyautogui.hotkey('alt', 's')
    time.sleep(2.0)  # 等待保存完成
def download_with_pyautogui():
    print("=" * 70)
    print("PyAutoGUI 自动化下载工具 (优化版)")
    print(f"目标保存路径: {save_path}")
    print(f"待下载文件数: {len(file_urls)}")
    print("=" * 70)
    print("\n⚠️  重要提示：")
    print("1. 脚本运行期间请勿操作鼠标键盘")
    print("2. 脚本会自动打开浏览器并操作")
    print("3. 如需中断，请将鼠标移动到屏幕左上角")
    print("\n3 秒后开始执行...")
    print("=" * 70, "\n")
    
    if not os.path.exists(save_path):
        os.makedirs(save_path)
        print(f"已创建目录: {save_path}\n")
    
    # 倒计时
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    
    success_count = 0
    fail_count = 0
    
    try:
        # 1. 处理第一个文件（需要设置路径）
        print(f"[1/{len(file_urls)}] 正在处理: {os.path.basename(file_urls[0])}")
        if open_edge_browser(file_urls[0]):
            save_file_via_keyboard(set_path=True)
            print(f"  ✓ {os.path.basename(file_urls[0])} - 已保存 (路径已设定)")
            success_count += 1
        else:
            print(f"  ✗ {os.path.basename(file_urls[0])} - 打开浏览器失败")
            fail_count += 1
        
        # 2. 处理后续文件（默认路径保存）
        for i in range(1, len(file_urls)):
            filename = os.path.basename(file_urls[i])
            print(f"[{i+1}/{len(file_urls)}] 正在处理: {filename}")
            
            try:
                pyautogui.hotkey('ctrl', 't')  # 打开新标签页
                time.sleep(1.5)
                
                type_url_via_clipboard(file_urls[i])
                
                # 后续文件不再设置路径，直接保存
                save_file_via_keyboard(set_path=False)
                
                print(f"  ✓ {filename} - 已保存 (使用默认路径)")
                success_count += 1
                
            except Exception as e:
                print(f"  ✗ {filename} - 失败: {str(e)}")
                fail_count += 1
        
        print("\n" + "=" * 70)
        print("下载任务完成!")
        print(f"总计: {len(file_urls)} 个文件")
        print(f"成功: {success_count} 个")
        print(f"失败: {fail_count} 个")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n发生严重错误: {str(e)}")
    
    finally:
        # 任务结束，关闭浏览器
        print("\n正在关闭浏览器...")
        time.sleep(1)
        pyautogui.hotkey('alt', 'f4')
        print("浏览器已关闭。")
        print("\n提示：请检查目标文件夹确认文件是否下载成功")
if __name__ == "__main__":
    download_with_pyautogui()