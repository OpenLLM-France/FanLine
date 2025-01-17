#!/usr/bin/env python3

import sys
import requests
import string
import json
import random
import time


class QueueAPI:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    @staticmethod
    def _post(url: str, params):
        r = requests.post(url, data=json.dumps(params), headers={'Content-Type': 'application/json'})
        if r.status_code not in [ 200 ]:
            print(url)
            print(r.status_code)
            raise Exception(str(r))
        return r

    @staticmethod
    def _get(url: str):
        r = requests.get(url)
        if r.status_code not in [ 200 ]:
            raise Exception(str(r))
        return r

    def join(self, uid: str):
        r = self._post(f'{self.host}:{self.port}/queue/join', { 'user_id': uid })

    def status(self, uid: str):
        #print(uid)
        r = self._get(f'{self.host}:{self.port}/queue/status/{uid}')
        return r.json()

    def confirm(self, uid: str):
        r = self._post(f'{self.host}:{self.port}/queue/confirm', { 'user_id': uid })
        return r.json()

    def leave(self, uid: str):
        r = self._post(f'{self.host}:{self.port}/queue/leave', { 'user_id': uid })
        return r.json()

    def metrics(self):
        r = self._get(f'{self.host}:{self.port}/queue/metircs')
        return r.json()


class Client:
    def __init__(self, pooling_interval: int, api: QueueAPI):
        self.pooling_interval = pooling_interval
        self.api = api
        self.uid = Client._get_random_uid()
        self.epsilon = 5

    @staticmethod
    def _get_random_uid(sz: int = 16):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=sz))

    # Wait for 'draft' in the status
    def _wait_in_queue(self):
        prev_pos = sys.maxsize
        while True:
            time.sleep(self.pooling_interval)
            out = self.api.status(self.uid)
            if out['status'] in [ 'draft' ]:
                break
            if out['status'] in [ 'waiting' ]:
                if int(out['position']) > prev_pos:
                    raise Exception(f'Position in the queue increased: {out["position"]} > {prev_pos}')
                prev_pos = int(out['position'])

    # Wait for 'disconnected' in the status after the expected_duration seconds
    def _wait_until_session_ends(self, expected_duration):
        session_start = time.time()
        while True:
            time.sleep(self.pooling_interval)
            out = self.api.status(self.uid)
            #print(out)

            now = time.time()
            elapsed = now - session_start
 
            if 'status' not in out or out['status'] in [ 'disconnected' ]:
                if elapsed + self.epsilon < expected_duration:
                    raise Exception(f'Session too short: {elapsed}s unstead of {expected_duration}s')
                break
            if 'status' not in out:
                raise Exception(f'Status unclear: "{out}"')
            if out['status'] in [ 'connected' ]:
                if elapsed - self.epsilon > expected_duration:
                    raise Exception(f'Session too long: {elapsed}s instead of {expected_duration}s')
                continue
            raise Exception(f'Unexpected status: {out}')


    def run(self):
        self.api.join(self.uid)

        self._wait_in_queue()

        out = self.api.confirm(self.uid)
        #print(out)
        expected_duration = out['session_duration']

        self._wait_until_session_ends(expected_duration)


def main(host: str, port: int, pooling_interval: int):
    api = QueueAPI(host, port)

    try:
         client = Client(pooling_interval, api)
         client.run()

    except Exception as e:
         sys.stderr.write(f'ERROR: {type(e)} {e}\n')
         return -1

    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", type=str, help="Queue host")
    parser.add_argument("-p", "--port", type=int, help="Queue port")
    parser.add_argument("-i", "--interval", type=int, help="Pooling interval")
    args = parser.parse_args()

    sys.exit(main('http://' + args.url, args.port, args.interval))

