"""
Connections to MySQL and MongoDB, shared by every Python script.

Settings come from environment variables, so no password is ever committed:
  MYSQL_HOST      (default: localhost)
  MYSQL_USER      (default: root)
  MYSQL_PASSWORD  (default: empty)
  MONGO_URI       (default: mongodb://localhost:27017)

Set them once per terminal before running a script, e.g.
  Windows (cmd):   set MYSQL_PASSWORD=yourpassword
  Mac / Linux:     export MYSQL_PASSWORD=yourpassword

Needs:  pip install mysql-connector-python pymongo
"""

"""Shared MySQL and MongoDB connections for the Pharma Counterfeit project."""

import os

DB_NAME = os.environ.get("DB_NAME", "pharma_counterfeit_db")


def get_mysql():
    """Open a MySQL connection using the active environment credentials."""
    import mysql.connector

    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=DB_NAME,
        autocommit=False,
    )


def get_mongo_db():
    """Return the active MongoDB database."""
    from pymongo import MongoClient

    client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    return client[DB_NAME]