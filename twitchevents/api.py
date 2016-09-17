import datetime
import logging
import threading
from pprint import pformat
from time import sleep

from twitch.api import v3 as twitch
from twitch.exceptions import ResourceUnavailableException
from twitch.logging import log as twitch_log


class twitchevents(object):

    def __init__(self, name_list):
        super(twitchevents, self).__init__()
        twitch_log.setLevel(logging.INFO)
        self.logger = logging.getLogger("twitchevents")
        self.thread = threading.Thread(target=self.run)
        self.follower_cache = {}
        self.running = False
        self.follower_callbacks = []
        self.streaming_start_callbacks = []
        self.streaming_stop_callbacks = []
        self.viewers_change_callbacks = []
        self.online_status = {}
        self.viewer_cache = {}
        for name in name_list:
            self.online_status[name] = False
            try:
                self.follower_cache[name] = {
                    f['user']['display_name'] or f['user']['name']
                    for f in twitch.follows.by_channel(
                        name, limit=100)['follows']
                }
            except ResourceUnavailableException:
                self.logger.warn("Twitch api unavailable during initializing")
                self.follower_cache[name] = set()

    def subscribe_new_follow(self, callback):
        self.follower_callbacks.append(callback)

    def subscribe_streaming_start(self, callback):
        self.streaming_start_callbacks.append(callback)

    def subscribe_streaming_stop(self, callback):
        self.streaming_stop_callbacks.append(callback)

    def subscribe_viewers_change(self, callback):
        self.viewers_change_callbacks.append(callback)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def run(self):
        self.logger.info("Starting twitch api polling")
        self.running = True
        self.next_stream_check = datetime.datetime.now()
        self.next_follower_check = datetime.datetime.now()
        if self.streaming_stop_callbacks or self.streaming_start_callbacks or self.follower_callbacks or self.viewers_change_callbacks:
            while self.running:
                if self.streaming_start_callbacks or self.streaming_stop_callbacks or self.viewers_change_callbacks:
                    if self.next_stream_check < datetime.datetime.now():
                        result = None
                        for name in self.online_status:
                            try:
                                result = twitch.streams.by_channel(name).get("stream")
                            except:
                                self.logger.exception("Error while grabbing stream for {0}".format(name))
                                continue
                            self.check_streaming(name, result)
                            self.check_viewers(name, result)
                        self.next_stream_check = datetime.datetime.now() + datetime.timedelta(seconds=20)
                if self.follower_callbacks:
                    if self.next_follower_check < datetime.datetime.now():
                        self.check_followers()
                        self.next_follower_check = datetime.datetime.now() + datetime.timedelta(seconds=60)
                sleep(0.5)

        else:
            self.logger.critical("Not starting, no callbacks registered")

    def check_streaming(self, name, result):
        if result:
            if not self.online_status[name]:
                self.online_status[name] = True
                for callback in self.streaming_start_callbacks:
                    callback(name)
        elif self.online_status[name]:
            self.online_status[name] = False
            for callback in self.streaming_stop_callbacks:
                callback(name)

    def check_followers(self):
        for streamer_name in self.online_status:
            result = None
            try:
                result = twitch.follows.by_channel(streamer_name, limit=100)
            except:
                self.logger.exception("Error while getting followers for {0}".format(streamer_name))
                continue
            latest_follows = {f['user']['display_name'] or f['user']['name'] for f in result['follows']}
            new_follows = latest_follows.difference(self.follower_cache[streamer_name])
            if new_follows:
                self.follower_cache[streamer_name].update(new_follows)
                for callback in self.follower_callbacks:
                    callback(new_follows, streamer_name, result['_total'])

    def check_viewers(self, name, result):
        if self.online_status[name]:
            if result:
                if name in self.viewer_cache:
                    if self.viewer_cache[name] != result['viewers']:
                        self.viewer_cache[name] = result['viewers']
                        for callback in self.viewers_change_callbacks:
                            callback(result['viewers'], name)
                else:
                    self.viewer_cache[name] = result['viewers']
                    for callback in self.viewers_change_callbacks:
                        callback(result['viewers'], name)

    def stop(self):
        self.logger.info("Attempting to stop twitch api polling")
        self.running = False
        if self.thread.is_alive():
            self.thread.join()
