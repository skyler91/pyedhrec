import json
import re
import requests

from .caching import commander_cache, card_detail_cache, combo_cache, average_deck_cache, deck_cache
from .utils import get_random_ua


class EDHRec:
    def __init__(self, cookies: str = None):
        self.cookies = cookies
        self.session = requests.Session()
        self.session.proxies
        if self.cookies:
            self.session.cookies = self.get_cookie_jar(cookies)
        self.session.headers = {
            "Accept": "application/json",
            "User-Agent": get_random_ua()
        }
        self.base_url = "https://edhrec.com"
        self._json_base_url = "https://json.edhrec.com/cards"
        self._api_base_url = f"{self.base_url}/api"
        self.default_build_id = "mI7k8IZ23x74LocK_h-qe"
        self.current_build_id = None

        self._commander_data_cache = {}

    @staticmethod
    def get_cookie_jar(cookie_str: str):
        if cookie_str.startswith("userState="):
            cookie_str = cookie_str.split("userState=")[1]

        d = {
            "userState": cookie_str
        }
        cookie_jar = requests.cookies.cookiejar_from_dict(d)
        return cookie_jar

    @staticmethod
    def format_card_name(card_name: str) -> str:
        # card names are all lower case
        card_name = card_name.lower()
        # Spaces need to be converted to underscores
        card_name = card_name.replace(" ", "-")
        # remove apostrophes
        card_name = card_name.replace("'", "")
        # remove commas
        card_name = card_name.replace(",", "")
        # remove double quotes
        card_name = card_name.replace('"', "")
        # If the name contains '//' (e.g. dfc) remove it
        return card_name.split('-//-')[0]

    def _get(self, uri: str, query_params: dict =None, return_type: str = "json") -> dict:
        res = self.session.get(uri, params=query_params)
        res.raise_for_status()
        if return_type == "json":
            res_json = res.json()
            return res_json
        else:
            return res.content

    def get_build_id(self) -> str or None:
        home_page = self._get(self.base_url, return_type="raw")
        home_page_content = home_page.decode("utf-8")
        script_block_regex = r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*)</script>"
        if script_match := re.findall(script_block_regex, home_page_content):
            props_str = script_match[0]
        else:
            return None
        try:
            props_data = json.loads(props_str)
            return props_data.get("buildId")
        except json.JSONDecodeError:
            return None

    def check_build_id(self):
        if not self.current_build_id:
            self.current_build_id = self.get_build_id()
            # If we couldn't get the current buildId we'll try to fall back to a known static string
            if not self.current_build_id:
                self.current_build_id = self.default_build_id
        # We have a build ID set
        return True

    def _build_nextjs_uri(self, endpoint: str, card_name: str, slug: str = None, theme: str = None, budget: str = None, filter: str = None):
        self.check_build_id()
        formatted_card_name = self.format_card_name(card_name)
        query_params = {
            "commanderName": formatted_card_name
        }
        uri = f"{self.base_url}/_next/data/{self.current_build_id}/{endpoint}/{formatted_card_name}"

        if theme:
            uri += f"/{theme}"
            if not budget:
                query_params["themeName"] = theme

        if budget == "budget":
            uri += f"/budget.json"
            query_params["themeName"] = budget
        elif budget == "expensive":
            uri += f"/expensive.json"
            query_params["themeName"] = budget
        else:
            uri += f".json"

        if slug:
            query_params["slug"] = slug

        if endpoint == "combos":
            query_params["colors"] = formatted_card_name

        if filter:
            query_params["f"] = filter

        return uri, query_params

    @staticmethod
    def _get_nextjs_data(response: dict) -> dict:
        if "pageProps" in response:
            return response.get("pageProps", {}).get("data")

    def _get_cardlist_from_container(self, card_name: str, tag: str = None, filter: str = None) -> dict:
        card_data = self.get_commander_data(card_name, filter)
        container = card_data.get("container", {})
        json_dict = container.get("json_dict", {})
        card_lists = json_dict.get("cardlists")
        result = {}
        for cl in card_lists:
            _card_list = cl.get("cardviews")
            _header = cl.get("header")
            _tag = cl.get("tag")
            if tag:
                if _tag == tag:
                    result[_header] = _card_list
                    return result
            else:
                result[_header] = _card_list
        return result

    def get_card_list(self, card_list: list) -> dict:
        uri = f"{self._api_base_url}/cards"
        req_body = {
            "format": "dict",
            "names": card_list
        }
        res = self.session.post(uri, json=req_body)
        res.raise_for_status()
        res_json = res.json()
        return res_json

    def get_card_link(self, card_name: str) -> str:
        formatted_card_name = self.format_card_name(card_name)
        uri = f"{self.base_url}/cards/{formatted_card_name}"
        return uri

    @card_detail_cache
    def get_card_details(self, card_name: str) -> dict:
        formatted_card_name = self.format_card_name(card_name)
        uri = f"{self._json_base_url}/{formatted_card_name}"
        res = self._get(uri)
        return res

    @combo_cache
    def get_card_combos(self, card_name: str) -> dict:
        combo_uri, params = self._build_nextjs_uri("combos", card_name)
        res = self._get(combo_uri, query_params=params)
        data = self._get_nextjs_data(res)
        return data

    def get_combo_url(self, combo_url: str) -> str:
        uri = f"{self.base_url}"
        if combo_url.startswith("/"):
            uri += combo_url
        else:
            uri += f"/{combo_url}"
        return uri

    @commander_cache
    def get_commander_data(self, card_name: str, filter: str = None) -> dict:
        commander_uri, params = self._build_nextjs_uri("commanders", card_name, filter=filter)
        res = self._get(commander_uri, query_params=params)
        data = self._get_nextjs_data(res)
        return data

    @average_deck_cache
    def get_commanders_average_deck(self, card_name: str, budget: str = None) -> dict:
        average_deck_uri, params = self._build_nextjs_uri("average-decks", card_name, budget=budget)
        res = self._get(average_deck_uri, query_params=params)
        data = self._get_nextjs_data(res)
        deck_obj = {
            "commander": card_name,
            "decklist": data.get("deck")
        }
        return deck_obj

    @deck_cache
    def get_commander_decks(self, card_name: str, budget: str = None) -> dict:
        average_deck_uri, params = self._build_nextjs_uri("decks", card_name, budget=budget)
        res = self._get(average_deck_uri, query_params=params)
        data = self._get_nextjs_data(res)
        return data

    def get_commander_cards(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name)
        return card_list

    def get_new_cards(self, card_name: str, filter: str = None) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "newcards", filter)
        return card_list

    def get_high_synergy_cards(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "highsynergycards")
        return card_list

    def get_top_cards(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "topcards")
        return card_list

    def get_top_creatures(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "creatures")
        return card_list

    def get_top_instants(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "instants")
        return card_list

    def get_top_sorceries(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "sorceries")
        return card_list

    def get_top_artifacts(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "utilityartifacts")
        return card_list

    def get_top_mana_artifacts(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "manaartifacts")
        return card_list

    def get_top_enchantments(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "enchantments")
        return card_list

    def get_top_battles(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "battles")
        return card_list

    def get_top_planeswalkers(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "planeswalkers")
        return card_list

    def get_top_lands(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "lands")
        return card_list

    def get_top_utility_lands(self, card_name: str) -> dict:
        card_list = self._get_cardlist_from_container(card_name, "utilitylands")
        return card_list
