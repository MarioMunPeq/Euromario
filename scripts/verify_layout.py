import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('http://localhost:8000', wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Check filters structure
        platforms = await page.locator('.filters__platforms .game-tile').count()
        games = await page.locator('.filters__games .game-tile').count()
        print(f'Platform tiles: {platforms}')
        print(f'Game tiles: {games}')
        
        # Check platform grid is 2x2
        platform_grid = await page.locator('.filters__platforms').evaluate(lambda el: {
            "gridTemplateColumns": el.style.gridTemplateColumns,
            "gridTemplateRows": el.style.gridTemplateRows
        })
        print(f'Platform grid: {platform_grid}')
        
        # Check games grid is 2 rows
        games_grid = await page.locator('.filters__games').evaluate(lambda el: {
            "gridTemplateRows": el.style.gridTemplateRows,
            "gridAutoFlow": el.style.gridAutoFlow,
            "gridAutoColumns": el.style.gridAutoColumns
        })
        print(f'Games grid: {games_grid}')
        
        # Test selection
        print("\n--- Testing selection ---")
        # Click a game tile
        await page.locator('.filters__games .game-tile').nth(1).click()
        await page.wait_for_timeout(500)
        active_game = await page.locator('.filters__games .game-tile.active').count()
        print(f'Active game tiles: {active_game}')
        
        # Click a platform tile
        await page.locator('.filters__platforms .game-tile').first.click()
        await page.wait_for_timeout(500)
        active_platform = await page.locator('.filters__platforms .game-tile.active').count()
        print(f'Active platform tiles: {active_platform}')
        
        # Check active styles (no bright border)
        active_style = await page.locator('.filters__games .game-tile.active').evaluate(lambda el: {
            "borderColor": window.getComputedStyle(el).borderColor,
            "backgroundColor": window.getComputedStyle(el).backgroundColor,
            "boxShadow": window.getComputedStyle(el).boxShadow
        })
        print(f'Active game style: {active_style}')
        
        await browser.close()

asyncio.run(test())