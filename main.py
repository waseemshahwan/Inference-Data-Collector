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

parser = argparse.ArgumentParser(description='Script to generate an unlabeled dataset for Poseidon')
parser.add_argument('--threads', dest='threads', action='store', type=int, default=1, help='How many browsers to run in parallel for collection')
parser.add_argument('--proxy-url', dest='proxy_url', action='store', type=str, required=False, help='The url of the proxy')
parser.add_argument('--proxy-port-min', dest='proxy_port_min', action='store', type=int, required=False, help='The minimum port (if one port then set --proxy-port-max to --proxy-port-min)')
parser.add_argument('--proxy-port-max', dest='proxy_port_max', action='store', type=int, required=False, help='The maximum port')
parser.add_argument('--proxy-user', dest='proxy_user', action='store', type=str, required=False, help='Username of proxy auth (if auth exists)')
parser.add_argument('--proxy-pass', dest='proxy_pass', action='store', type=str, required=False, help='Password of proxy auth (if auth exists)')
args = parser.parse_args()

if args.proxy_url and (args.proxy_port_min is None or args.proxy_port_max is None):
    parser.error("--proxy-url requires --proxy-port-min and --proxy-port-max.")
if args.proxy_url and len([x for x in (args.proxy_user,args.proxy_pass) if x is not None]) == 1:
    parser.error("--proxy-user and --proxy-pass must be given together.")

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

    proxy = None
    if args.proxy_url is not None:
        if args.proxy_user is not None:
            proxy = 'http://{}:{}@{}:{}'.format(args.proxy_user, args.proxy_pass, args.proxy_url, random.randint(args.proxy_port_min, args.proxy_port_max))
        else:
            proxy = 'http://{}:{}'.format(args.proxy_url, random.randint(args.proxy_port_min, args.proxy_port_max))
        
    async with session.request(method=method, url=url, data=post_data_buffer, headers=headers, proxy=proxy) as response:
        content_type = response.headers.get('content-type')
        
        print(response.status, response.url)
        return await route.fulfill(body=await response.read(), content_type=content_type, status=response.status, headers=response.headers)


async def main_async():
    async with aiohttp.ClientSession() as session:
        async with async_playwright() as p:
            iphone_11 = p.devices["iPhone 11 Pro"]
            browser = await p.webkit.launch(headless=False, devtools=True)

            context = await browser.new_context(
                **iphone_11,
                locale="en-US",
                geolocation={"longitude": 12.492507, "latitude": 41.889938 },
                permissions=["geolocation"],
            )

            page = await context.new_page()

            async def load_page():
                if len(list(filter(lambda x: 'bframe' in x.url, page.main_frame.child_frames))) > 0:
                    bframe = list(filter(lambda x: 'bframe' in x.url, page.main_frame.child_frames))[0]
                    print(bframe)
                    el = await bframe.wait_for_selector('.rc-button-reload')
                    await el.click()
                else:
                    try:
                        await page.goto(LANDING)
                        el = await page.wait_for_selector('#submit')
                        await el.click()
                    except Exception:
                        return await load_page()

            async def ensure_image(response):
                if '/api2/payload' in response.url:
                    asyncio.ensure_future(download_image(response))
                elif '/api2/userverify' not in response.url: return
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
                    
                    return await load_page()
                    # return await check_labels(frame)

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
    for i in range(args.threads):
        Thread(target=main).start()
        