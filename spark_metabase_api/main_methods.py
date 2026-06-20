import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_TIMEOUT = 30


def _build_http_session() -> requests.Session:
    """Session with retry on transient errors (idempotent verbs only).

    Long-running exports against large Metabase instances frequently hit
    'Remote end closed connection without response' as the proxy reaps
    keep-alive sockets. urllib3.Retry handles this transparently: connection
    errors and 5xx are retried with exponential backoff. POST is left
    single-shot to avoid duplicate writes.
    """
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "PUT", "DELETE")),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


class Metabase_API:
    def __init__(self, domain, email=None, password=None, session_id=None, basic_auth=False, is_admin=True):
        self.domain = domain.rstrip("/")
        self.email = email
        self.password = password
        self.session_id = session_id
        self.header = {"X-Metabase-Session": self.session_id} if self.session_id else None
        self.auth = (self.email, self.password) if basic_auth else None
        self.is_admin = is_admin
        self.session_expiry = None
        self._http = _build_http_session()

        if not (self.email and self.password) and not self.session_id:
            raise ValueError("You must provide either email/password or a valid session ID.")

        if not self.is_admin:
            print(
                """
                Ask your Metabase admin to disable "Friendly Table and Field Names" (in Admin Panel > Settings > General).
                Without this some of the functions of the current package may not work as expected.
                """
            )

        # Validate session ID or authenticate
        if not self.session_id or not self.is_session_valid():
            self.authenticate()

    def is_session_valid(self):
        """Check if the session ID is valid"""
        if not self.header:
            return False
        try:
            response = self._http.get(
                self.domain + "/api/user/current",
                headers=self.header,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def authenticate(self):
        """Get a Session ID"""
        if not self.email or not self.password:
            raise ValueError("Email and password are required for authentication.")

        conn_header = {"username": self.email, "password": self.password}
        res = self._http.post(
            self.domain + "/api/session",
            json=conn_header,
            auth=self.auth,
            timeout=DEFAULT_TIMEOUT,
        )

        if not res.ok:
            raise Exception(f"Authentication failed: {res.text}")

        self.session_id = res.json()["id"]
        self.header = {"X-Metabase-Session": self.session_id}

        # Print session ID to the user
        print(f"Authenticated successfully. Your session ID is: {self.session_id}")


    def validate_session(self):
        """Re-authenticate if the current session has expired."""
        if self.is_session_valid():
            return True
        self.authenticate()
        return True

    # import REST Methods
    from ._rest_methods import get, post, put, delete

    # import helper functions
    from ._helper_methods import (
        get_item_info,
        get_item_id,
        get_item_name,
        get_db_id_from_table_id,
        get_db_info,
        get_table_metadata,
        get_columns_name_id,
        friendly_names_is_disabled,
        verbose_print,
        check_collection,
        get_dashboard_question_ids,
        find_cards_via_db_object,
        get_user_coll_id
    )

    ##################################################################
    ###################### Custom Functions ##########################
    ##################################################################
    from .create_methods import create_card, create_collection, create_segment
    from .copy_methods import copy_card, copy_collection, copy_dashboard
    from .modify_methods import restrict_collection_access, restrict_filter_with_card_values

    def search(self, q, item_type=None, archived=False):
        """
        Search for Metabase objects and return their basic info.
        We can limit the search to a certain item type by providing a value for item_type keyword.

        Keyword arguments:
        q -- search input
        item_type -- to limit the search to certain item types (default:None, means no limit)
        archived -- whether to include archived items in the search
        """
        assert item_type in [
            None,
            "card",
            "dashboard",
            "collection",
            "table",
            "segment",
            "metric",
        ]
        assert archived in [True, False]

        # Metabase 0.50+ rejects Python's capitalized 'False'/'True' bool URL
        # serialization with a 400 'should be a boolean, received: "False"'.
        # Send the explicit lowercase string instead.
        res = self.get(
            endpoint="/api/search/",
            params={"q": q, "archived": str(archived).lower()},
        )
        if not res:
            return []
        if type(res) == dict:  # paginated shape introduced in *.40.0
            res = res.get("data") or []
        if item_type is not None:
            res = [item for item in res if item.get("model") == item_type]

        return res

    def get_card_data(
        self,
        card_name=None,
        card_id=None,
        collection_name=None,
        collection_id=None,
        data_format="json",
        parameters=None,
    ):
        """
        Run the query associated with a card and get the results.
        The data_format keyword specifies the format of the returned data:
            - 'json': every row is a dictionary of <column-header, cell> key-value pairs
            - 'csv': the entire result is returned as a string, where rows are separated by newlines and cells with commas.
        To pass the filter values use 'parameters' param:
            The format is like [{"type":"category","value":["val1","val2"],"target":["dimension",["template-tag","filter_variable_name"]]}]
            See the network tab when exporting the results using the web interface to get the proper format pattern.
        """
        assert data_format in ["json", "csv"]
        if parameters:
            assert type(parameters) == list

        if card_id is None:
            if card_name is None:
                raise ValueError("Either card_id or card_name must be provided.")
            card_id = self.get_item_id(
                item_name=card_name,
                collection_name=collection_name,
                collection_id=collection_id,
                item_type="card",
            )

        # add the filter values (if any)
        params_json = {"parameters": json.dumps(parameters or [])}

        # get the results
        res = self.post(
            "/api/card/{}/query/{}".format(card_id, data_format),
            "raw",
            data=params_json,
        )

        # return the results in the requested format
        if data_format == "json":
            return json.loads(res.text)
        if data_format == "csv":
            return res.text.replace("null", "")

    def run_query(self, dataset_query, parameters=None):
        """Run an ad-hoc dataset_query (POST /api/dataset) and return parsed JSON.

        dataset_query is the shape stored in a card's definition:
            {"database": <id>, "type": "native"|"query", "native"|"query": {...}}
        """
        body = dict(dataset_query)
        body["parameters"] = parameters or []
        res = self.post("/api/dataset", "raw", json=body)
        try:
            return res.json()
        except Exception:
            return {"status": "failed", "error": "non-JSON response ({})".format(
                getattr(res, "status_code", "?"))}

    def clone_card(
        self,
        card_id,
        source_table_id=None,
        target_table_id=None,
        source_table_name=None,
        target_table_name=None,
        new_card_name=None,
        new_card_collection_id=None,
        ignore_these_filters=None,
        return_card=False,
    ):
        """
        *** work in progress ***
        Create a new card where the source of the old card is changed from 'source_table_id' to 'target_table_id'.
        The filters that were based on the old table would become based on the new table.
        In the current version of the function there are some limitations which would be removed in future versions:
            - The column names used in filters need to be the same in the source and target table (except the ones that are ignored by 'ignore_these_filters' param).
            - The source and target tables need to be in the same DB.

        Keyword arguments:
        card_id -- id of the card
        source_table_id -- The table that the filters of the card are based on
        target_table_id -- The table that the filters of the cloned card would be based on
        new_card_name -- Name of the cloned card. If not provided, the name of the source card is used.
        new_card_collection_id -- The id of the collection that the cloned card should be saved in
        ignore_these_filters -- A list of variable names of filters. The source of these filters would not change in the cloning process.
        return_card -- Whether to return the info of the created card (default False)
        """
        # Make sure we have the data we need
        if not source_table_id:
            if not source_table_name:
                raise ValueError(
                    "Either the name or id of the source table needs to be provided."
                )
            else:
                source_table_id = self.get_item_id("table", source_table_name)

        if not target_table_id:
            if not target_table_name:
                raise ValueError(
                    "Either the name or id of the target table needs to be provided."
                )
            else:
                target_table_id = self.get_item_id("table", target_table_name)

        if ignore_these_filters:
            assert type(ignore_these_filters) == list

        # Fetch the card info. Force MBQL 4 on Metabase 0.57+ so we keep the
        # 'field-id'/'field' shapes this method understands.
        card_info = self.get(
            "/api/card/{}".format(card_id),
            params={"legacy-mbql": "true"},
        )
        if not card_info:
            raise ValueError('There is no card with the id "{}"'.format(card_id))

        dataset_query = card_info.get("dataset_query") or {}
        query_type = dataset_query.get("type")
        if query_type not in ("native", "query"):
            raise ValueError(
                "Card {} has no usable dataset_query (type={!r}); "
                "clone_card only supports native and MBQL queries."
                .format(card_id, query_type)
            )

        # get the mappings, both name -> id and id -> name
        target_table_col_name_id_mapping = self.get_columns_name_id(
            table_id=target_table_id
        )
        source_table_col_id_name_mapping = self.get_columns_name_id(
            table_id=source_table_id, column_id_name=True
        )

        # native questions
        if query_type == "native":
            filters_data = card_info["dataset_query"]["native"]["template-tags"]
            # change the underlying table for the card
            if not source_table_name:
                source_table_name = self.get_item_name("table", source_table_id)
            if not target_table_name:
                target_table_name = self.get_item_name("table", target_table_id)
            card_info["dataset_query"]["native"]["query"] = card_info["dataset_query"][
                "native"
            ]["query"].replace(source_table_name, target_table_name)
            # change filters source
            for filter_variable_name, data in filters_data.items():
                if (
                    ignore_these_filters is not None
                    and filter_variable_name in ignore_these_filters
                ):
                    continue
                column_id = data["dimension"][1]
                column_name = source_table_col_id_name_mapping[column_id]
                target_col_id = target_table_col_name_id_mapping[column_name]
                card_info["dataset_query"]["native"]["template-tags"][
                    filter_variable_name
                ]["dimension"][1] = target_col_id

        # simple/custom questions
        elif query_type == "query":
            query_data = card_info["dataset_query"]["query"]

            # change the underlying table for the card
            query_data["source-table"] = target_table_id

            # walk the MBQL tree and remap column ids in-place; safer than
            # round-tripping through repr/eval which breaks on quotes/unicode.
            def _remap_field_ids(node):
                if isinstance(node, list):
                    if (
                        len(node) >= 2
                        and node[0] in ("field", "field-id")
                        and isinstance(node[1], int)
                    ):
                        col_name = source_table_col_id_name_mapping.get(node[1])
                        if col_name in target_table_col_name_id_mapping:
                            node[1] = target_table_col_name_id_mapping[col_name]
                    for item in node:
                        _remap_field_ids(item)
                elif isinstance(node, dict):
                    for value in node.values():
                        _remap_field_ids(value)

            _remap_field_ids(query_data)
            card_info["dataset_query"]["query"] = query_data

        new_card_json = {}
        for key in ["dataset_query", "display", "visualization_settings"]:
            new_card_json[key] = card_info[key]

        if new_card_name:
            new_card_json["name"] = new_card_name
        else:
            new_card_json["name"] = card_info["name"]

        if new_card_collection_id:
            new_card_json["collection_id"] = new_card_collection_id
        else:
            new_card_json["collection_id"] = card_info["collection_id"]

        if return_card:
            return self.create_card(
                custom_json=new_card_json, verbose=True, return_card=return_card
            )
        else:
            self.create_card(custom_json=new_card_json, verbose=True)

    def move_to_archive(
        self,
        item_type,
        item_name=None,
        item_id=None,
        collection_name=None,
        collection_id=None,
        table_id=None,
        verbose=False,
    ):
        """Archive the given item. For deleting the item use the 'delete_item' function."""
        assert item_type in ["card", "dashboard", "collection", "segment"]

        if not item_id:
            if not item_name:
                raise ValueError(
                    "Either the name or id of the {} must be provided.".format(
                        item_type
                    )
                )
            if item_type == "collection":
                item_id = self.get_item_id("collection", item_name)
            elif item_type == "segment":
                item_id = self.get_item_id("segment", item_name, table_id=table_id)
            else:
                item_id = self.get_item_id(
                    item_type, item_name, collection_id, collection_name
                )

        if item_type == "segment":
            # 'revision_message' is mandatory for archiving segments
            res = self.put(
                "/api/{}/{}".format(item_type, item_id),
                json={"archived": True, "revision_message": "archived!"},
            )
        else:
            res = self.put(
                "/api/{}/{}".format(item_type, item_id), json={"archived": True}
            )

        if res in [
            200,
            202,
        ]:  # for segments the success status code returned is 200 for others it is 202
            self.verbose_print(verbose, "Successfully Archived.")
        else:
            print("Archiving Failed.")

        return res

    def delete_item(
        self,
        item_type,
        item_name=None,
        item_id=None,
        collection_name=None,
        collection_id=None,
        verbose=False,
    ):
        """
        Delete the given item. Use carefully (this is different from archiving).
        Currently Collections and Segments cannot be deleted using the Metabase API.
        """
        assert item_type in ["card", "dashboard"]
        if not item_id:
            if not item_name:
                raise ValueError(
                    "Either the name or id of the {} must be provided.".format(
                        item_type
                    )
                )
            item_id = self.get_item_id(
                item_type, item_name, collection_id, collection_name
            )

        return self.delete("/api/{}/{}".format(item_type, item_id))

    def add_card_to_dashboard(self, card_id, dashboard_id):
        """
        Append a card to a dashboard.

        Tries the legacy POST /api/dashboard/:id/cards first (single call,
        still supported on Metabase up to ~0.54) and falls back to PUT
        /api/dashboard/:id with the full dashcards array on newer versions
        where the legacy endpoint is gone. Returns None on success (matching
        the original signature) and raises if both paths fail.
        """
        legacy_res = self.post(
            "/api/dashboard/{}/cards".format(dashboard_id),
            "raw",
            json={"cardId": card_id},
        )
        if legacy_res.ok:
            return

        dashboard = self.get("/api/dashboard/{}".format(dashboard_id))
        if not dashboard:
            raise ValueError(
                "Could not load dashboard {} (legacy POST returned {} and the "
                "GET to fall back to PUT also failed)."
                .format(dashboard_id, legacy_res.status_code)
            )
        dashcards = list(dashboard.get("dashcards") or dashboard.get("ordered_cards") or [])
        max_row = max((dc.get("row", 0) + dc.get("size_y", 0) for dc in dashcards), default=0)
        dashcards.append({
            "id": -1,
            "card_id": card_id,
            "row": max_row,
            "col": 0,
            "size_x": 24,
            "size_y": 8,
            "parameter_mappings": [],
            "visualization_settings": {},
        })
        self.put(
            "/api/dashboard/{}".format(dashboard_id),
            json={"dashcards": dashcards},
        )

    @staticmethod
    def make_json(raw_json, prettyprint=False):
        """Turn the string copied from the Inspect->Network window into a Dict."""
        ret_dict = json.loads(raw_json)
        if prettyprint:
            import pprint
            pprint.pprint(ret_dict)
        return ret_dict

    def rescan_object_values(
            self,
            object_type=None,
            object_id=None,
            verbose=False,
        ):
            """
            Manually trigger an update for the FieldValues for this Field/Table.
            Only applies to Fields that are eligible for FieldValues.
            """
            assert object_type in ["table", "field"]
            if not object_id:
                raise ValueError("id of the field or table must be provided.")
            
            self.verbose_print(verbose, 'Rescan {} values ...'.format(object_type))
            return self.post("/api/{}/{}/rescan_values".format(object_type, str(object_id)))
    
    def rescan_db_field_values(
            self,
            db_id=None,
            verbose=False,
        ):
            """
            Trigger a manual scan of the field values for this Database.
            """
            if not db_id:
                raise ValueError("id of the database must be provided.")
            
            self.verbose_print(verbose, 'Rescan database field values triggered...')
            return self.post("/api/database/{}/rescan_values".format(db_id))

    def rescan_db_sync_schemas(
            self,
            db_id=None,
            verbose=False,
        ):
            """
            Trigger a manual update of the schema metadata for this Database.
            """
            if not db_id:
                raise ValueError("id of the database must be provided.")
            
            self.verbose_print(verbose, 'Update database schema metadata triggered...')
            return self.post("/api/database/{}/sync_schema".format(db_id))
    