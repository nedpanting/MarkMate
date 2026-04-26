
# MarkMate - Database Layer

import sqlite3
import os


class DatabaseError(Exception):  # Used by routes when a database rule fails (e.g. duplicate category name)
    pass

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
DB_PATH = os.path.join(BASE_DIR, "content.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql") 


class Database:
    def __init__(self, db_path=DB_PATH):  # Optional path for testing
        self.db_path = db_path 


    # Connection management

    def connect(self): # Connect to the database
        conn = sqlite3.connect(self.db_path, timeout = 5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # Initialisation

    def initialise(self): # Create database tables from schema.sql
        if not os.path.exists(SCHEMA_PATH):
            raise Exception("Schema file not found")

        with open(SCHEMA_PATH, "r") as file: 
            schema = file.read()

        conn = self.connect()
        conn.executescript(schema)
        conn.close()

    # Core helpers

    def execute_write(self, query, params=()): #Execute a write operation and return the last inserted row ID
        conn = self.connect()
        cursor = conn.execute(query, params)
        conn.commit()
        conn.close()
        return cursor.lastrowid # 

    def fetch_one(self, query, params=()): #Execute a query and return the first row
        conn = self.connect()
        cursor = conn.execute(query, params)
        result = cursor.fetchone()
        conn.close()
        return result

    def fetch_all(self, query, params=()): #Execute a query and return all rows
        conn = self.connect()
        cursor = conn.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results

 
    # User operations


    def create_user(self, username, password_hash): # Create a new user
        query = "INSERT INTO Users (Username, PasswordHash) VALUES (?, ?)"
        return self.execute_write(query, (username, password_hash))

    def get_user_by_username(self, username): # Get a user by username
        query = "SELECT * FROM Users WHERE Username = ?"
        return self.fetch_one(query, (username,))

    def get_user_by_id(self, user_id): # Get a user by ID 
        query = "SELECT * FROM Users WHERE UserID = ?"
        return self.fetch_one(query, (user_id,))

    def delete_user(self, user_id): # Permanently remove user 
        query = "DELETE FROM Users WHERE UserID = ?"
        self.execute_write(query, (user_id,))

    def get_user_settings(self, user_id): # Loads settings or inserts defaults if this user has none yet
        query = "SELECT * FROM UserSettings WHERE UserID = ?"
        settings = self.fetch_one(query, (user_id,))
        if settings:
            return settings

        # Create default settings if they don't exist
        default_insert = """
        INSERT OR IGNORE INTO UserSettings
        (UserID, Theme, AutoTagging, ClearLibraryOnDelete, AccountDeletionConfirm)
        VALUES (?, 'light', 1, 0, 1)
        """
        self.execute_write(default_insert, (user_id,))
        return self.fetch_one(query, (user_id,))

    def update_user(self, user_id, theme, autotagging, clear_library, account_deletion): # Update a user's settings
        query = """
        INSERT INTO UserSettings
        (UserID, Theme, AutoTagging, ClearLibraryOnDelete, AccountDeletionConfirm)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(UserID) DO UPDATE SET
            Theme = excluded.Theme,
            AutoTagging = excluded.AutoTagging,
            ClearLibraryOnDelete = excluded.ClearLibraryOnDelete,
            AccountDeletionConfirm = excluded.AccountDeletionConfirm
        """
        self.execute_write( query,(user_id, theme, autotagging, clear_library, account_deletion),)
        return True

    
    # Content operations 
   

    @staticmethod
    def normalize_url_for_duplicate_check(url):
        """Strip, drop trailing slashes, lowercase — matches SQL duplicate check."""
        s = (url or "").strip()
        if not s:
            return ""
        return s.rstrip("/").lower()

    def user_has_saved_url(self, user_id, url):
        """True if this user already has an active (non-deleted) item with the same URL."""
        norm = self.normalize_url_for_duplicate_check(url)
        if not norm:
            return False
        query = """
            SELECT 1 FROM Content
            WHERE UserID = ? AND IsDeleted = 0
              AND lower(rtrim(trim(URL), '/')) = ?
            LIMIT 1
        """
        return self.fetch_one(query, (user_id, norm)) is not None

    def create_content(self, user_id, url, title, platform, notes, thumbnail, category_id): # Create a new content item
        query = """
        INSERT INTO Content (UserID, URL, Title, Platform, Notes, Thumbnail, CategoryID)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        return self.execute_write(query, (user_id, url, title, platform, notes, thumbnail, category_id))

    def get_all_content(self, user_id): # Get all content for a user
        query = """
        SELECT c.*, cat.CategoryName
        FROM Content c
        LEFT JOIN Categories cat ON c.CategoryID = cat.CategoryID
        WHERE c.UserID = ? AND c.IsDeleted = 0
        ORDER BY c.DateSaved DESC
        """
        return self.fetch_all(query, (user_id,))

    def get_content_count_by_platform(self, user_id): # Distinct platforms with counts (for filters)
        query = """
        SELECT Platform, COUNT(*) AS total
        FROM Content
        WHERE UserID = ? AND IsDeleted = 0 AND Platform IS NOT NULL AND TRIM(Platform) != ''
        GROUP BY Platform
        ORDER BY Platform
        """
        return self.fetch_all(query, (user_id,))

    def search_content(
        self,
        user_id,
        query_term=None,
        platform=None,
        tag_name=None,
        category_id=None,
        sort_by="newest",
    ): 
        query_term = (query_term or "").strip()
        platform = (platform or "").strip()
        tag_name = (tag_name or "").strip().lower()

        allowed_sort = {"newest": "c.DateSaved DESC", "oldest": "c.DateSaved ASC", "title": "c.Title COLLATE NOCASE ASC"}
        order_clause = allowed_sort.get(sort_by, "c.DateSaved DESC")

        conditions = ["c.UserID = ?", "c.IsDeleted = 0"]
        params = [user_id]

        if query_term:
            like = "%" + query_term.lower() + "%"
            conditions.append(
                "(LOWER(c.Title) LIKE ? OR LOWER(IFNULL(c.Notes, '')) LIKE ? OR LOWER(c.URL) LIKE ?)"
            )
            params.extend([like, like, like])

        if platform:
            conditions.append("c.Platform = ?")
            params.append(platform)

        if category_id is not None:
            conditions.append("c.CategoryID = ?")
            params.append(category_id)

        if tag_name:
            conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM ContentTags ct
                    JOIN Tags t ON t.TagID = ct.TagID
                    WHERE ct.ContentID = c.ContentID AND t.UserID = ? AND t.TagName = ?
                )
                """
            )
            params.extend([user_id, tag_name])

        where_sql = " AND ".join(conditions)
        query = f"""
        SELECT c.*, cat.CategoryName
        FROM Content c
        LEFT JOIN Categories cat ON c.CategoryID = cat.CategoryID
        WHERE {where_sql}
        ORDER BY {order_clause}
        """
        return self.fetch_all(query, tuple(params))

    def get_all_tags(self, user_id): # All tag names for this user (e.g. search dropdown)
        query = "SELECT TagName FROM Tags WHERE UserID = ? ORDER BY TagName COLLATE NOCASE" # collate nocase makes something case insensitive 
        return self.fetch_all(query, (user_id,))

    def update_content(self, content_id, user_id, title, notes, category_id): # Update a content item
        query = """
        UPDATE Content
        SET Title = ?, Notes = ?, CategoryID = ?
        WHERE ContentID = ? AND UserID = ? AND IsDeleted = 0
        """
        self.execute_write(query, (title, notes, category_id, content_id, user_id))

    def delete_content(self, content_id, user_id):  # deletes one piece of content, while still removing tag relationships so no orphaned links
        conn = self.connect()
        try:
            conn.execute( # Remove tag relationships, finds content with matching content ID and user, and deletes the rows in contenttags linked to it
                """
                DELETE FROM ContentTags WHERE ContentID IN (
                    SELECT ContentID FROM Content WHERE ContentID = ? AND UserID = ?
                )
                """,
                (content_id, user_id),
            )
            conn.execute( #soft delete content
                "UPDATE Content SET IsDeleted = 1 WHERE ContentID = ? AND UserID = ?",
                (content_id, user_id),
            )
            conn.commit()
        finally:
            conn.close()

    soft_delete_content = delete_content  # name expected by routes blueprint

    def delete_all_content_for_user(self, user_id):  # Soft-delete every saved item for this user
        conn = self.connect()
        try:
            conn.execute( # Remove ALL tag links 
                """
                DELETE FROM ContentTags WHERE ContentID IN (
                    SELECT ContentID FROM Content WHERE UserID = ? AND IsDeleted = 0
                )
                """,
                (user_id,),
            )
            conn.execute( # soft delete everything 
                "UPDATE Content SET IsDeleted = 1 WHERE UserID = ? AND IsDeleted = 0",
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # Category operations
    

    def create_category(self, user_id, name): # Create a new category
        query = "INSERT INTO Categories (UserID, CategoryName) VALUES (?, ?)"
        return self.execute_write(query, (user_id, name))

    def get_categories(self, user_id): # Get all categories for a user
        query = "SELECT * FROM Categories WHERE UserID = ?"
        return self.fetch_all(query, (user_id,))

    def get_category_by_name(self, user_id, name): # Lookup category by name (case-insensitive)
        if not name or not str(name).strip():
            return None
        query = """
        SELECT * FROM Categories
        WHERE UserID = ? AND LOWER(TRIM(CategoryName)) = LOWER(TRIM(?))
        """
        return self.fetch_one(query, (user_id, name))

    def delete_category(self, category_id, user_id): # Delete a category
        query = "DELETE FROM Categories WHERE CategoryID = ? AND UserID = ?"
        self.execute_write(query, (category_id, user_id))

    def get_category_by_id(self, category_id, user_id): # Get one category if it belongs to this user
        query = "SELECT * FROM Categories WHERE CategoryID = ? AND UserID = ?"
        return self.fetch_one(query, (category_id, user_id))

    def update_category(self, category_id, user_id, name): # Rename a category
        query = """
        UPDATE Categories
        SET CategoryName = ?
        WHERE CategoryID = ? AND UserID = ?
        """
        self.execute_write(query, (name, category_id, user_id))

    def get_categories_with_counts(self, user_id): # Categories with how many saved items use each
        query = """
        SELECT c.CategoryID, c.CategoryName,
               COUNT(co.ContentID) AS total
        FROM Categories c
        LEFT JOIN Content co
            ON c.CategoryID = co.CategoryID
            AND co.UserID = ?
            AND co.IsDeleted = 0
        WHERE c.UserID = ?
        GROUP BY c.CategoryID, c.CategoryName
        ORDER BY c.CategoryName
        """
        return self.fetch_all(query, (user_id, user_id))

    # Tag operations
    

    def get_or_create_tag(self, user_id, tag_name): # Get or create a tag
        tag_name = tag_name.lower().strip()

        insert = "INSERT OR IGNORE INTO Tags (UserID, TagName) VALUES (?, ?)"
        self.execute_write(insert, (user_id, tag_name))

        query = "SELECT TagID FROM Tags WHERE UserID = ? AND TagName = ?"
        row = self.fetch_one(query, (user_id, tag_name))
        return row["TagID"]

    def add_tag_to_content(self, content_id, tag_id): # Add a tag to a content item
        query = "INSERT OR IGNORE INTO ContentTags (ContentID, TagID) VALUES (?, ?)"
        self.execute_write(query, (content_id, tag_id)) 

    def get_tags_for_content(self, content_id): # Get all tags for a content item
        query = """
        SELECT t.TagName
        FROM Tags t
        JOIN ContentTags ct ON t.TagID = ct.TagID
        WHERE ct.ContentID = ?
        """
        return self.fetch_all(query, (content_id,)) # Return all tags for a content item

    def get_tag_by_id(self, tag_id, user_id): # Get one tag row if it belongs to this user
        query = "SELECT * FROM Tags WHERE TagID = ? AND UserID = ?"
        return self.fetch_one(query, (tag_id, user_id))

    def get_tags_with_usage(self, user_id): # All tags with how many items use each
        query = """
        SELECT t.TagID, t.TagName,
               COUNT(DISTINCT ct.ContentID) AS total
        FROM Tags t
        LEFT JOIN ContentTags ct ON t.TagID = ct.TagID
        LEFT JOIN Content co
            ON ct.ContentID = co.ContentID
            AND co.UserID = ?
            AND co.IsDeleted = 0
        WHERE t.UserID = ?
        GROUP BY t.TagID, t.TagName
        ORDER BY t.TagName
        """
        return self.fetch_all(query, (user_id, user_id))

    def delete_tag(self, tag_id, user_id): # Remove a tag and its links 
        query = "DELETE FROM Tags WHERE TagID = ? AND UserID = ?"
        self.execute_write(query, (tag_id, user_id))
