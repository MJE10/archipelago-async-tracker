import asyncio
import logging
import traceback
from collections.abc import Callable
from CommonClient import CommonContext, gui_enabled, get_base_parser, server_loop, ClientCommandProcessor, handle_url_arg
import os
import time
import json
import sys
from typing import Union, Any, TYPE_CHECKING


from BaseClasses import CollectionState, MultiWorld, LocationProgressType, ItemClassification, Location
from worlds.generic.Rules import exclusion_rules
from Utils import __version__, output_path, open_filename,async_start
from worlds import AutoWorld
from . import TrackerWorld, UTMapTabData, CurrentTrackerState,UT_VERSION
from .TrackerCore import TrackerCore
from collections import Counter, defaultdict
from MultiServer import mark_raw
from NetUtils import NetworkItem

from . import TrackerCore

from Generate import main as GMain, mystery_argparse

# logger = logging.getLogger("Client")

DEBUG = False
ITEMS_HANDLING = 0b111
UT_MAP_TAB_KEY = "UT_MAP"


class TrackerGameContext(CommonContext):
    game = ""
    tags = CommonContext.tags | {"Tracker"}
    command_processor = None
    tracker_page = None
    map_page = None
    tracker_world: UTMapTabData | None = None
    coord_dict: dict[int, list] = {}
    deferred_dict: dict[str, list] = {}
    ldeferred_dict: dict[str,list] = {}
    map_page_coords_func = lambda *args: {}
    watcher_task = None
    update_callback: Callable[[list[str]], bool] | None = None
    region_callback: Callable[[list[str]], bool] | None = None
    events_callback: Callable[[list[str]], bool] | None = None
    glitches_callback: Callable[[list[str]], bool] | None = None
    gen_error = None
    output_format = "Both"
    hide_excluded = False
    use_split = True
    re_gen_passthrough = None
    local_items: list[NetworkItem] = []
    checksums = {}

    _auto_tab = True

    @property
    def auto_tab(self):
        return self._auto_tab

    @auto_tab.setter
    def auto_tab(self, value):
        self._auto_tab = value
        self.ui.auto_tab = value
        if value:
            self.load_map(None)
            self.updateTracker()

    @property
    def tracker_items_received(self):
        if not (self.items_handling & 0b010):
            return self.items_received + self.local_items
        else:
            return self.items_received

    def update_tracker_items(self):
        self.local_items = [self.locations_info[location] for location in self.checked_locations
                            if location in self.locations_info and
                            self.locations_info[location].player == self.slot]

    def __init__(self, server_address, password, no_connection: bool = True, print_list: bool = False, print_count: bool = False):
        if no_connection:
            from worlds import network_data_package
            self.item_names = self.NameLookupDict(self, "item")
            self.location_names = self.NameLookupDict(self, "location")
            self.update_data_package(network_data_package)
        else:
            super().__init__(server_address, password)
        self.items_handling = ITEMS_HANDLING
        self.quit_after_update = print_list or print_count
        self.print_list = print_list
        self.print_count = print_count
        self.location_icon = None
        self.root_pack_path = None
        self.map_id = None
        self.defered_entrance_datastorage_keys = []
        self.defered_entrance_callback = None
        self.tracker_core = TrackerCore.TrackerCore(None,print_list,print_count)

    def updateTracker(self) -> CurrentTrackerState:
        if self.disconnected_intentionally: return CurrentTrackerState.init_empty_state()
        self.tracker_core.set_missing_locations([]) # todo
        with open("/app/Archipelago/Players/data/missing_checks.json", "r") as f:
            self.tracker_core.set_missing_locations(json.loads(f.read()))
        self.tracker_core.set_items_received([]) # todo
        with open("/app/Archipelago/Players/data/items_received.json", "r") as f:
            items = []
            for i in json.loads(f.read()):
                items.append(NetworkItem(*i))
            self.tracker_core.set_items_received(items)
        self.tracker_core.player_id = 1
        self.tracker_core.set_hints({})
        datapack_path = "/app/Archipelago/Players/data/datapackage.json"
        if os.path.exists(datapack_path):
            with open(datapack_path, "r") as f:
                datapackage = json.loads(f.read())
                self.tracker_core.multiworld.worlds[1].item_id_to_name = {}
                for name in datapackage["item_name_to_id"]:
                    self.tracker_core.multiworld.worlds[1].item_id_to_name[datapackage["item_name_to_id"][name]] = name
                self.tracker_core.multiworld.worlds[1].location_id_to_name = {}
                for name in datapackage["location_name_to_id"]:
                    self.tracker_core.multiworld.worlds[1].item_id_to_name[datapackage["location_name_to_id"][name]] = name
        try:
            updateTracker_ret = self.tracker_core.updateTracker()
        except Exception as e:
            print("Failed to update tracker")
            return
        if updateTracker_ret.state is None:
            return updateTracker_ret # core.updateTracker failed, just pass it along
        if self.quit_after_update:
            if self.print_list:
                print("In logic list:")
                for i in updateTracker_ret.readable_locations:
                    print(i)

        return updateTracker_ret

    def run_generator(self):
        self.tracker_core.run_generator(None, None)
        self.use_split = self.tracker_core.use_split #fancy hack

async def main(args):
    ctx = TrackerGameContext(args.connect, args.password, print_count=args.count, print_list=args.list)
    ctx.auth = args.name
    ctx.run_generator()
    ctx.updateTracker()


def launch(*args):
    parser = get_base_parser(description="Gameless Archipelago Client, for text interfacing.")
    parser.add_argument('--name', default=None, help="Slot Name to connect as.")
    if sys.stdout:  # If terminal output exists, offer gui-less mode
        parser.add_argument('--count', default=False, action='store_true', help="just return a count of in logic checks")
        parser.add_argument('--list', default=False, action='store_true', help="just return a list of in logic checks")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    args = handle_url_arg(parser.parse_args(args))

    # if args.nogui and (args.count or args.list):
    #     from logging import ERROR
        # logger.setLevel(ERROR)

    asyncio.run(main(args))
