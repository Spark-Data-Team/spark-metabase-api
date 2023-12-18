
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
            print("Either the name of id of the collection must be provided.")
        if collection_name == "Root":
            collection_id = None
        else:
            collection_id = self.get_item_id(
                "collection", collection_name
            )

    # Enable access only to the Administrators group
    collections_graph = self.get('/api/collection/graph')
    for group in collections_graph["groups"]:
        # Check if the group is not in the list of enabled groups
        if int(group) not in authorized_group_ids: # Convert group to integer for comparison
            for collection in collections_graph["groups"][group].keys():
                if collection == str(collection_id):
                    collections_graph["groups"][group][collection] = 'none' # Remove access

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
        verbose=False
):
    """
    Redirect dashboard/question filter dropdown list to "from another model or question"
    This function assumes the filter is a field filter.
    
    Keyword arguments:
    item_type -- 'question' or 'dashboard' 
    item_id -- ID of the Metabase element
    filter_name -- Name of the filter as it appears on Metabase
    card_id -- ID of the card from which the dropdown list will be sourced
    card_column_name -- The name of the column where to find the values in the "source" card
    new_filter_name -- (Optional) give a new name to the filter
    verbose -- prints extra information (default False)
    """
        
    clean_filter_name = filter_name.lower().strip()
    clean_card_column_name = card_column_name.upper().strip()
    
    # Add security layer to make sure item_type is dashboard or card only
    item = self.get('/api/{}/{}'.format(item_type, item_id))

    filter_found = False
    
    for param in item["parameters"]:
        clean_param_name = param["name"].lower().strip()
        if clean_filter_name in clean_param_name:
            filter_found = True
            if new_filter_name is not None:
                param["name"] = new_filter_name 
            param["values_source_type"] = "card"
            param["values_source_config"] = {
                "card_id": int(card_id),
                "value_field": [
                    "field",
                    clean_card_column_name,
                    {
                        "base-type": "type/Text"
                    }
                ]
            }
    
    if not filter_found and verbose:
        self.verbose_print(verbose, 'No filter found with the name "{}".'.format(filter_name))
    else:
        self.verbose_print(verbose, 'Modify filter "{}" ...'.format(filter_name))
        self.put('/api/{}/{}'.format(item_type, item_id), json=item)
