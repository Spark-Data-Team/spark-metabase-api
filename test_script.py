from spark_metabase_api import Metabase_API

mb = Metabase_API('https://spark.metabaseapp.com/', session_id='60cccc2a-cafb-4839-aac6-d8f1b9f1924a')

DASHBOARD_TEMPLATE_ID = 11751
NANGA_PARENT_COLLECTION_ID = 5239

""" to debug
res = mb.restrict_filter_with_card_values(
    item_type='dashboard',
    item_id==11751,
    filter_name="Client",
    card_id=17099, # client_filter - Nanga
    card_column_name="client_name"
)
print(res)
"""

dash_template_to_duplicate = mb.get_item_info(
    item_type='dashboard',
    item_id=DASHBOARD_TEMPLATE_ID
)
print(dash_template_to_duplicate)
"""
dash_template_to_duplicate = mb.get_item_info(
    item_type='dashboard',
    item_id=DASHBOARD_TEMPLATE_ID
)

print(dash_template_to_duplicate["name"])
dashboard_name = dash_template_to_duplicate["name"]

existing_collection_id  = mb.check_collection(
    collection_name=dashboard_name,
    parent_collection_id=NANGA_PARENT_COLLECTION_ID, # Nanga collection
)

if not existing_collection_id:

    new_collection = mb.create_collection(
            collection_name=dashboard_name,
            parent_collection_id=NANGA_PARENT_COLLECTION_ID, # Nanga collection
            official=True,
            return_results=True,
        )

    new_collection_id = new_collection['id']

    # To adapt
    dup_dashboard_id, question_copies_collection_id = mb.copy_dashboard(
            source_dashboard_id=11751, 
            destination_dashboard_name="test 3 wrong place",
            destination_collection_id=128,
            collection_position=1,
            deepcopy=False
    )
    print(dup_dashboard_id, question_copies_collection_id)


    new_subcollection = mb.create_collection(
            collection_name="Questions",
            parent_collection_id=new_collection_id, 
            official=False,
            return_results=True,
        )
    
    new_subcollection_id = new_subcollection['id']

    
else:
    print("Collection already exists")


# Get current collections graph (requested before put request)
res = requests.get(f"{METABASE_URL}/api/collection/graph", headers = headers)
assert res.ok == True
collections_graph = res.json()
print(collections_graph)

# Remove access to the newly created collection to everyone (except admins)
for group in collections_graph["groups"]:
    if group != '2': # Administrators group
        for collection in collections["groups"][group].keys():
            if collection == str(client_collection_id):
                collections["groups"][group][collection] = 'none' # Remove access
"""

"""
res = mb.restrict_collection_access(
    collection_id=new_collection_id,
    authorized_group_ids=[2],
    return_results=True
)
"""
"""
res = mb.restrict_collection_access(
    collection_id=5287,#new_subcollection_id,
    authorized_group_ids=[2],
    return_results=True
)
print(res)
"""




"""

DESTINATION_DASHBOARD_NAME = 
nanga_client_col_id = 

dup_dashboard_id, question_copies_collection_id = mb.copy_dashboard(
        source_dashboard_id=DASHBOARD_ID, 
        destination_dashboard_name=DESTINATION_DASHBOARD_NAME,
        destination_collection_id=nanga_client_col_id,
        deepcopy=True
)
"""


"""
CLIENT_NAME = 'Modz'
NANGA_PARENT_COLLECTION_ID = 5231
DASHBOARD_ID = 6629
DESTINATION_DASHBOARD_NAME = 'Test Louis'

nanga_client_col_id  = mb.check_collection(
    collection_name=CLIENT_NAME,
    parent_collection_id=NANGA_PARENT_COLLECTION_ID, # Nanga collection
)

if not nanga_client_col_id:
    res = mb.create_collection(
            collection_name=CLIENT_NAME,
            parent_collection_id=NANGA_PARENT_COLLECTION_ID, # Nanga collection
            return_results=True,
        )
    nanga_client_col_id = res['id']

dup_dashboard_id, question_copies_collection_id = mb.copy_dashboard(
        source_dashboard_id=DASHBOARD_ID, 
        destination_dashboard_name=DESTINATION_DASHBOARD_NAME,
        destination_collection_id=nanga_client_col_id,
        deepcopy=True
)

dash = mb.get_item_info(
    item_type='dashboard',
    item_id=dup_dashboard_id
)

dash_card_ids = []
for dc in dash['ordered_cards']:
    if (dc["card_id"] != None):
        mb = mb.put(f"api/card/{dc['card_id']}",
            json = {'collection_id':question_copies_collection_id}
        )
        assert mb.ok == True

update_dash = False
# Iterate over dashboard parameters
for dash_filter in dash['parameters']:
    # Check if 'default' key exists and if 'slug' contains specific items
    if any(slug_item in dash_filter["slug"] for slug_item in ['client']):
        dash_filter['default'] = CLIENT_NAME
        update_dash = True

if update_dash:
    # Force the default value of the filter Client to be CLIENT_NAME
    res = mb.put('/api/dashboard/{}'.format(dash['id']), json=dash)

"""