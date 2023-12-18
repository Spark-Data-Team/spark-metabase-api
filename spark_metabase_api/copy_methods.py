
def copy_card(self, source_card_name=None, source_card_id=None, 
                source_collection_name=None, source_collection_id=None,
                destination_card_name=None, 
                destination_collection_name=None, destination_collection_id=None,
                postfix='', verbose=False):
    """
    Copy the card with the given name/id to the given destination collection. 

    Keyword arguments:
    source_card_name -- name of the card to copy (default None) 
    source_card_id -- id of the card to copy (default None) 
    source_collection_name -- name of the collection the source card is located in (default None) 
    source_collection_id -- id of the collection the source card is located in (default None) 
    destination_card_name -- name used for the card in destination (default None).
                                                        If None, it will use the name of the source card + postfix.
    destination_collection_name -- name of the collection to copy the card to (default None) 
    destination_collection_id -- id of the collection to copy the card to (default None) 
    postfix -- if destination_card_name is None, adds this string to the end of source_card_name 
                            to make destination_card_name
    """
    ### Making sure we have the data that we need 
    if not source_card_id:
        if not source_card_name:
            raise ValueError('Either the name or id of the source card must be provided.')
        else:
            source_card_id = self.get_item_id(item_type='card',
                                                item_name=source_card_name, 
                                                collection_id=source_collection_id, 
                                                collection_name=source_collection_name)

    if not destination_collection_id:
        if not destination_collection_name:
            raise ValueError('Either the name or id of the destination collection must be provided.')
        else:
            destination_collection_id = self.get_item_id('collection', destination_collection_name)

    if not destination_card_name:
        if not source_card_name:
            source_card_name = self.get_item_name(item_type='card', item_id=source_card_id)
        destination_card_name = source_card_name + postfix

    # Get the source card info
    source_card = self.get('/api/card/{}'.format(source_card_id))

    # Update the name and collection_id
    card_json = source_card
    card_json['collection_id'] = destination_collection_id
    card_json['name'] = destination_card_name

    # Fix the issue #10
    if card_json.get('description') == '': 
        card_json['description'] = None

    # Save as a new card
    res = self.create_card(custom_json=card_json, verbose=verbose, return_card=True)

    # Return the id of the created card
    return res['id']



def copy_dashboard(self, 
                   source_dashboard_name=None, 
                source_dashboard_id=None, 
                source_collection_name=None, 
                source_collection_id=None,
                destination_dashboard_name=None, 
                destination_collection_name=None, 
                destination_collection_id=None,
                collection_position=None,
                deepcopy=False, 
                postfix=''
            ):
    """
    Copy the dashboard with the given name/id to the given destination collection. 

    Keyword arguments:
    source_dashboard_name -- name of the dashboard to copy (default None) 
    source_dashboard_id -- id of the dashboard to copy (default None) 
    source_collection_name -- name of the collection the source dashboard is located in (default None) 
    source_collection_id -- id of the collection the source dashboard is located in (default None) 
    destination_dashboard_name -- name used for the dashboard in destination (default None).
                                                                If None, it will use the name of the source dashboard + postfix.
    destination_collection_name -- name of the collection to copy the dashboard to (default None) 
    destination_collection_id -- id of the collection to copy the dashboard to (default None) 
    collection_position -- Ping the dashboard in the collection
    deepcopy -- whether to duplicate the cards inside the dashboard (default False).
                            If True, puts the duplicated cards in a collection called "[dashboard_name]'s cards" 
                            in the same path as the duplicated dashboard.
    postfix -- if destination_dashboard_name is None, adds this string to the end of source_dashboard_name 
                            to make destination_dashboard_name
    """
    ### making sure we have the data that we need 
    if not source_dashboard_id:
        if not source_dashboard_name:
            raise ValueError('Either the name or id of the source dashboard must be provided.')
        else:
            source_dashboard_id = self.get_item_id(item_type='dashboard',item_name=source_dashboard_name, 
                                                    collection_id=source_collection_id, 
                                                    collection_name=source_collection_name)

    if not destination_collection_id:
        if not destination_collection_name:
            raise ValueError('Either the name or id of the destination collection must be provided.')
        else:
            destination_collection_id = self.get_item_id('collection', destination_collection_name)

    if not destination_dashboard_name:
        if not source_dashboard_name:
            source_dashboard_name = self.get_item_name(item_type='dashboard', item_id=source_dashboard_id)
        destination_dashboard_name = source_dashboard_name + postfix

    ### shallow-copy
    shallow_copy_json = {'collection_id':destination_collection_id, 'name':destination_dashboard_name, 'is_deep_copy':deepcopy}
    
    # Check if collection_position is an integer and not None
    if isinstance(collection_position, int) and collection_position is not None:
        shallow_copy_json['collection_position'] = collection_position

    res = self.post('/api/dashboard/{}/copy'.format(source_dashboard_id), json=shallow_copy_json)
    dup_dashboard_id = res['id']

    if deepcopy:
        questions_collection_name = "Questions"
        question_copies_collection_id = None

        try:
            question_copies_collection_id = self.get_item_id('collection', questions_collection_name)
        except ValueError as e:
            if 'There is no collection with the name' in str(e):
                # Collection not found, create it
                res = self.create_collection(
                    collection_name=questions_collection_name,
                    parent_collection_id=destination_collection_id,
                    return_results=True,
                )
                question_copies_collection_id = res['id']
                print(f"Sub-collection created: ID {question_copies_collection_id}")
            else:
                # If the error is due to some other reason, re-raise it
                raise

        else:
            # Collection exists, proceed with your logic if needed
            print("Sub-collection already exists: ID", question_copies_collection_id)

        return dup_dashboard_id, question_copies_collection_id
    
    return dup_dashboard_id, None


## NEED REWORK FOR THE DASHBOARD PART
def copy_collection(self, source_collection_name=None, source_collection_id=None, 
                    destination_collection_name=None,
                    destination_parent_collection_name=None, destination_parent_collection_id=None, 
                    deepcopy_dashboards=False, postfix='', child_items_postfix='', verbose=False):
    """
    Copy the collection with the given name/id into the given destination parent collection. 

    Keyword arguments:
    source_collection_name -- name of the collection to copy (default None) 
    source_collection_id -- id of the collection to copy (default None) 
    destination_collection_name -- the name to be used for the collection in the destination (default None).
                                                                    If None, it will use the name of the source collection + postfix.
    destination_parent_collection_name -- name of the destination parent collection (default None). 
                                                                                This is the collection that would have the copied collection as a child.
                                                                                use 'Root' for the root collection.
    destination_parent_collection_id -- id of the destination parent collection (default None).
                                                                            This is the collection that would have the copied collection as a child.
    deepcopy_dashboards -- whether to duplicate the cards inside the dashboards (default False). 
                                                    If True, puts the duplicated cards in a collection called "[dashboard_name]'s duplicated cards" 
                                                    in the same path as the duplicated dashboard.
    postfix -- if destination_collection_name is None, adds this string to the end of source_collection_name to make destination_collection_name.
    child_items_postfix -- this string is added to the end of the child items' names, when saving them in the destination (default '').
    verbose -- prints extra information (default False) 
    """
    ### making sure we have the data that we need 
    if not source_collection_id:
        if not source_collection_name:
            raise ValueError('Either the name or id of the source collection must be provided.')
        else:
            source_collection_id = self.get_item_id('collection', source_collection_name)

    if not destination_parent_collection_id:
        if not destination_parent_collection_name:
            raise ValueError('Either the name or id of the destination parent collection must be provided.')
        else:
            destination_parent_collection_id = (
                self.get_item_id('collection', destination_parent_collection_name)
                if destination_parent_collection_name != 'Root'
                else None
            )

    if not destination_collection_name:
        if not source_collection_name:
            source_collection_name = self.get_item_name(item_type='collection', item_id=source_collection_id)
        destination_collection_name = source_collection_name + postfix

    ### create a collection in the destination to hold the contents of the source collection
    res = self.create_collection(destination_collection_name, 
                                    parent_collection_id=destination_parent_collection_id, 
                                    parent_collection_name=destination_parent_collection_name,
                                    return_results=True
                                )
    destination_collection_id = res['id']    

    ### get the items to copy
    items = self.get('/api/collection/{}/items'.format(source_collection_id))
    if type(items) == dict:  # in Metabase version *.40.0 the format of the returned result for this endpoint changed
        items = items['data']

    ### copy the items of the source collection to the new collection
    for item in items:

        ## copy a collection
        if item['model'] == 'collection':
            collection_id = item['id']
            collection_name = item['name'] 
            destination_collection_name = collection_name + child_items_postfix
            self.verbose_print(verbose, 'Copying the collection "{}" ...'.format(collection_name))
            self.copy_collection(source_collection_id=collection_id,
                                    destination_parent_collection_id=destination_collection_id,
                                    child_items_postfix=child_items_postfix,
                                    deepcopy_dashboards=deepcopy_dashboards,
                                    verbose=verbose)

        ## copy a dashboard
        if item['model'] == 'dashboard':
            dashboard_id = item['id']
            dashboard_name = item['name']
            destination_dashboard_name = dashboard_name + child_items_postfix
            self.verbose_print(verbose, 'Copying the dashboard "{}" ...'.format(dashboard_name))
            self.copy_dashboard(source_dashboard_id=dashboard_id,
                                destination_collection_id=destination_collection_id,
                                destination_dashboard_name=destination_dashboard_name,
                                deepcopy=deepcopy_dashboards)

        ## copy a card
        if item['model'] == 'card':
            card_id = item['id']
            card_name = item['name']
            destination_card_name = card_name + child_items_postfix
            self.verbose_print(verbose, 'Copying the card "{}" ...'.format(card_name))
            self.copy_card(source_card_id=card_id,
                            destination_collection_id=destination_collection_id,
                            destination_card_name=destination_card_name)

