from datetime import datetime
from unittest.mock import (patch, MagicMock)
import pytest

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from mysql.connector.connection_cext import CMySQLConnection
import mysql.connector as mysql

from crawler.db import (
    create_import_record,
    create_mongo_client,
    get_mongo_collection,
    get_mongo_db,
    create_mysql_connection,
    run_mysql_executemany_query,
)
from crawler.helpers import LoggingCollection
from crawler.sql_queries import SQL_MLWH_MULTIPLE_INSERT

def test_create_mongo_client(config):
    assert type(create_mongo_client(config)) == MongoClient


def test_get_mongo_db(mongo_client):
    config, mongo_client = mongo_client
    assert type(get_mongo_db(config, mongo_client)) == Database


def test_get_mongo_collection(mongo_database):
    _, mongo_database = mongo_database
    collection_name = "test_collection"
    test_collection = get_mongo_collection(mongo_database, collection_name)
    assert type(test_collection) == Collection
    assert test_collection.name == collection_name


def test_create_import_record(freezer, mongo_database):
    config, mongo_database = mongo_database
    import_collection = mongo_database["imports"]

    docs = [{"x": 1}, {"y": 2}, {"z": 3}]
    error_collection = LoggingCollection()
    error_collection.add_error("TYPE 4", "error1")
    error_collection.add_error("TYPE 5", "error2")

    for centre in config.CENTRES:
        now = datetime.now().isoformat(timespec="seconds")
        result = create_import_record(
            import_collection, centre, len(docs), "test", error_collection.get_messages_for_import()
        )
        import_doc = import_collection.find_one({"_id": result.inserted_id})

        assert import_doc["date"] == now
        assert import_doc["centre_name"] == centre["name"]
        assert import_doc["csv_file_used"] == "test"
        assert import_doc["number_of_records"] == len(docs)
        assert import_doc["errors"] == error_collection.get_messages_for_import()

def test_create_mysql_connection_none(config):
    with patch('mysql.connector.connect', return_value = None):
        assert create_mysql_connection(config) == None

def test_create_mysql_connection_exception(config):
    # For example, if the credentials in the config are wrong
    with patch('mysql.connector.connect', side_effect = Exception('Boom!')):
        with pytest.raises(Exception):
            create_mysql_connection(config)

def test_run_mysql_executemany_query_success(config):
    conn = CMySQLConnection()

    conn.cursor = MagicMock()
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    cursor = conn.cursor.return_value
    cursor.executemany = MagicMock()
    cursor.close = MagicMock()

    run_mysql_executemany_query(mysql_conn=conn, sql_query=SQL_MLWH_MULTIPLE_INSERT, values=['test'])

    # check transaction is committed
    assert conn.commit.called == True

    # check connection is closed
    assert cursor.close.called == True
    assert conn.close.called == True

def test_run_mysql_executemany_query_execute_error(config):
    conn = CMySQLConnection()

    conn.cursor = MagicMock()
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    cursor = conn.cursor.return_value
    cursor.executemany = MagicMock(side_effect = Exception('Boom!'))
    cursor.close = MagicMock()

    with pytest.raises(Exception):
        run_mysql_executemany_query(mysql_conn=conn, sql_query=SQL_MLWH_MULTIPLE_INSERT, values=['test'])

        # check transaction is not committed
        assert conn.commit.called == False

        # check connection is closed
        assert cursor.close.called == True
        assert conn.close.called == True
