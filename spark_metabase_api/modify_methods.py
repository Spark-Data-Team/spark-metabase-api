
def restrict_collection_access(
    self,
    collection_id=None,
    collection_name=None,
    authorized_group_ids=[],
    verbose=False
):
    """
    TO-DO/nice to have: adapt the function to have a bool parameter to restrict also access to sub-collections

    Enable access to a collection to only some Metabase groups.
    
    Keyword arguments:
    collection_id -- the ID of collection to restrict access to.
    authorized_group_ids -- a list of integers containing the authorized groups
    verbose -- prints extra information (default False) 
    """
    
    # Making sure we have the data we need
    if not collection_id:
        if not collection_name:
            raise ValueError("Either the name or id of the collection must be provided.")
        if collection_name == "Root":
            collection_id = None
        else:
            collection_id = self.get_item_id(
                "collection", collection_name
            )

    # Enforce 'none' for every group that isn't in the authorized list.
    # Since Metabase 0.56.13 the graph no longer carries explicit 'none' entries
    # so we must always set the key (instead of only updating an existing one).
    collections_graph = self.get('/api/collection/graph')
    target_key = str(collection_id)
    for group in collections_graph["groups"]:
        if int(group) in authorized_group_ids:
            continue
        collections_graph["groups"][group][target_key] = 'none'

    self.verbose_print(verbose, 'Restrict access to the collection "{}" ...'.format(collection_id))
    res = self.put('/api/collection/graph', json=collections_graph)
    

def restrict_filter_with_card_values(
        self,
        item_type,
        item_id,
        filter_name,
        card_id,
        card_column_name,
        new_filter_name=None,
        remove_default=False,
        column_base_type="type/Text",
        preserve_column_case=False,
        verbose=False
):
    """
    Redirect dashboard/question filter dropdown list to "from another model or question".
    This function assumes the filter is a field filter.

    Keyword arguments:
    item_type -- 'question' or 'dashboard'
    item_id -- ID of the Metabase element
    filter_name -- Name of the filter as it appears on Metabase
    card_id -- ID of the card from which the dropdown list will be sourced
    card_column_name -- The name of the column where to find the values in the "source" card.
    new_filter_name -- (Optional) give a new name to the filter
    remove_default -- (Optional) remove the default values of the filter
    column_base_type -- (Optional) Metabase base-type of the source column (default 'type/Text').
                        Use 'type/Integer', 'type/Float', 'type/Date', etc. for non-text columns.
    preserve_column_case -- (Optional, default False) by default the column name is upper-cased
                            (Snowflake-friendly). Set True for case-sensitive databases such as
                            Postgres/MySQL where identifiers are typically lowercased.
    verbose -- prints extra information (default False)
    """

    if item_type not in ('question', 'card', 'dashboard'):
        raise ValueError("item_type must be 'question', 'card' or 'dashboard'.")

    clean_filter_name = filter_name.lower().strip()
    clean_card_column_name = (
        card_column_name.strip() if preserve_column_case else card_column_name.upper().strip()
    )

    if item_type == 'question':
        item_type = 'card'  # avoid this easy mistake

    item = self.get('/api/{}/{}'.format(item_type, item_id))

    filter_found = False

    for param in item["parameters"]:
        clean_param_name = param["name"].lower().strip()
        if clean_filter_name in clean_param_name:
            filter_found = True
            if new_filter_name is not None:
                param["name"] = new_filter_name
            if remove_default:
                param["default"] = None
            param["values_source_type"] = "card"
            param["values_source_config"] = {
                "card_id": int(card_id),
                "value_field": [
                    "field",
                    clean_card_column_name,
                    {"base-type": column_base_type},
                ],
            }

    if not filter_found and verbose:
        self.verbose_print(verbose, 'No filter found with the name "{}".'.format(filter_name))
    else:
        self.verbose_print(verbose, 'Modify filter "{}" ...'.format(filter_name))
        self.put('/api/{}/{}'.format(item_type, item_id), json=item)
