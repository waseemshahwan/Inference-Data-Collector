from os import device_encoding
import sys
import asyncio
import requests
import time
import aiohttp
import json
import random
import argparse
from threading import Thread
from playwright.async_api import async_playwright

arguments = argparse.ArgumentParser()

LANDING="https://recaptcha-demo.appspot.com/recaptcha-v2-invisible.php"

async def download_image(response):
    with open('parts/' + str(time.time_ns()) + str(random.randint(0, 10000)) + '.jpeg', 'wb') as f:
        f.write(await response.body())

async def capture_route(session, route):
    request = route.request
    headers = request.headers
    method = request.method
    post_data_buffer = request.post_data_buffer
    url = request.url

    if LANDING in url:
        with open('document.html') as doc:
            return await route.fulfill(body=doc.read(), content_type='text/html', status=200, headers={ 'Access-Control-Allow-Origin': '*' })

    async with session.request(method=method, url=url, data=post_data_buffer, headers=headers) as response:
        content_type = response.headers.get('content-type')
        
        print(response.status, response.url)
        return await route.fulfill(body=await response.read(), content_type=content_type, status=response.status, headers=response.headers)


async def main_async():
    async with aiohttp.ClientSession() as session:
        async with async_playwright() as p:
            iphone_11 = p.devices["iPhone 11 Pro"]
            browser = await p.webkit.launch(headless=True, devtools=True)

            context = await browser.new_context(
                **iphone_11,
                locale="en-US",
                geolocation={"longitude": 12.492507, "latitude": 41.889938 },
                permissions=["geolocation"],
            )

            page = await context.new_page()

            async def load_page():
                await page.goto(LANDING)
                el = await page.wait_for_selector('#submit')
                await el.click()

            async def ensure_image(response):
                if '/api2/payload' in response.url:
                    await download_image(response)
                elif '/api2/userverify' in response.url:
                    await load_page()
            
            async def check_labels(frame):
                if 'bframe' in frame.url:
                    el = await frame.wait_for_selector('strong')
                    label = await el.text_content()
                    with open('labels.json', "r+") as f:
                        try:
                            data = json.loads(f.read())
                        except Exception:
                            data = []
                                                
                        if label not in data:
                            data.append(label)
                        
                        f.seek(0)
                        f.write(json.dumps(data))
                        f.truncate()
                    
                    await load_page()

            await page.route('**', lambda route: asyncio.ensure_future(capture_route(session, route)))
            page.on('response', lambda response: asyncio.ensure_future(ensure_image(response)))
            page.on('framenavigated', lambda frame: asyncio.ensure_future(check_labels(frame)))

            await load_page()

            print('Press CTRL-D to stop')
            reader = asyncio.StreamReader()
            pipe = sys.stdin
            loop = asyncio.get_event_loop()
            await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), pipe)
            async for line in reader:
                print(f'Got: {line.decode()!r}')

def main():
    asyncio.run(main_async())

if __name__ == '__main__':

    for i in range(5):
        Thread(target=main).start()
        