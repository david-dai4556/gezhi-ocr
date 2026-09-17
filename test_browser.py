"""Browser end-to-end validation using the installed Microsoft Edge."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from openpyxl import load_workbook

ROOT = Path(__file__).parent
OUT = ROOT / 'test-output'
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1080}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:18657')
    page.screenshot(path=str(OUT/'界面-初始.png'), full_page=True)
    page.locator('#file').set_input_files(str(OUT/'中文表格示例.png'))
    page.locator('#recognize').click()
    page.wait_for_function("document.querySelector('#dimensions').textContent === '4 行 × 3 列'", timeout=60000)
    page.locator('td[aria-label="B2"]').fill('浏览器中校对')
    page.screenshot(path=str(OUT/'界面-识别结果.png'), full_page=True)
    with page.expect_download() as event:
        page.locator('#export').click()
    event.value.save_as(OUT/'浏览器导出.xlsx')
    book = load_workbook(OUT/'浏览器导出.xlsx')
    assert book.active['B2'].value == '浏览器中校对'
    assert book.active['C2'].value == '00123'
    assert book.active['C2'].data_type == 's'
    page.locator('#addRow').click()
    page.locator('#addCol').click()
    assert page.locator('#dimensions').inner_text() == '5 行 × 4 列'
    page.locator('td[aria-label="D5"]').fill('新增')
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#deleteRow').click()
    assert page.locator('#dimensions').inner_text() == '4 行 × 4 列'
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(OUT/'界面-窄屏.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    browser.close()
print('BROWSER_E2E_OK: image upload, Chinese OCR, cell edit, XLSX download/readback, row/column editing, responsive layout, no JS errors')
