from spark_metabase_api import Metabase_API

mb = Metabase_API(
    "https://spark.metabaseapp.com/", session_id="60cccc2a-cafb-4839-aac6-d8f1b9f1924a"
)

DASHBOARD_TEMPLATE_ID = 11751
NANGA_PARENT_COLLECTION_ID = 5239

dashboard_question_ids = mb.get_dashboard_question_ids(dashboard_id=DASHBOARD_TEMPLATE_ID)

dup_dashboard_id, question_copies_collection_id, dashboard_question_ids = mb.copy_dashboard(
        source_dashboard_id=DASHBOARD_TEMPLATE_ID,
        destination_dashboard_name="Test Louis",
        destination_collection_id=128,
        collection_position=1,
        deepcopy=True,
    )


"""
mb.restrict_filter_with_card_values(
    item_type='dashboard',
    item_id=DASHBOARD_TEMPLATE_ID,
    filter_name="brand",
    card_id=17099, # client_filter - Nanga
    card_column_name="client_name",
    new_filter_name="Brand",
    verbose=True
)


mb.restrict_filter_with_card_values(
    item_type='dashboard',
    item_id=DASHBOARD_TEMPLATE_ID,
    filter_name="account name",
    card_id=17100, # account_name filter - Nanga
    card_column_name="account_name",
    verbose=True
)
"""

"""
dash_template_to_duplicate = mb.get_item_info(
    item_type="dashboard", item_id=DASHBOARD_TEMPLATE_ID
)

print(dash_template_to_duplicate["name"])
dashboard_name = dash_template_to_duplicate["name"]

existing_collection_id = mb.check_collection(
    collection_name=dashboard_name,
    parent_collection_id=NANGA_PARENT_COLLECTION_ID,  # Nanga collection
)

if not existing_collection_id:
    new_collection = mb.create_collection(
        collection_name=dashboard_name,
        parent_collection_id=NANGA_PARENT_COLLECTION_ID,  # Nanga collection
        official=True,
        return_results=True,
    )

    new_collection_id = new_collection["id"]

    # To adapt
    dup_dashboard_id, question_copies_collection_id = mb.copy_dashboard(
        source_dashboard_id=11751,
        destination_dashboard_name="test 3 wrong place",
        destination_collection_id=128,
        collection_position=1,
        deepcopy=False,
    )
    print(dup_dashboard_id, question_copies_collection_id)


else:
    print("Collection already exists")


res = mb.restrict_collection_access(
    collection_id=new_collection_id, authorized_group_ids=[2], return_results=True
)
"""