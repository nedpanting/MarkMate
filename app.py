# Main application file
# This file is responsible for initializing the database and starting the application

import logging
import os
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash  # Hash and check passwords

from database import Database
from Services.validator import ValidationError, validate_password, validate_username, validate_url

# Logger setup for debugging and error tracking
logger = logging.getLogger(__name__)

# Base directory setup for static and template folders
_BASE = os.path.dirname(os.path.abspath(__file__))

# Create Flask application instance
app = Flask(
    __name__,
    static_folder=os.path.join(_BASE, "static"),
    template_folder=os.path.join(_BASE, "templates"),
)

# Secret key for session management
app.secret_key = "your_secret_key"

# Create and initialise database
db = Database()
db.initialise()


@app.template_filter("uk_date")
def uk_date_filter(value):
    """UK display: day/month/year (DD/MM/YYYY) from SQLite ISO strings."""
    if value is None or value == "":
        return ""
    s = str(value).strip()
    try:
        if len(s) >= 19 and s[10] == " ":
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        elif len(s) >= 10:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        else:
            return s
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return s[:10] if len(s) >= 10 else s


@app.template_filter("thumb_url")
def thumb_url_filter(item): # Stored thumbnial or derived Youtube preview URL for display 
    from Services.metadata import derive_thumbnail_url

    if not item:
        return ""

    # Query results are sqlite3.Row, not always dict.
    try:
        thumbnail = item["Thumbnail"]
    except Exception:
        thumbnail = ""

    if thumbnail:
        return thumbnail

    try:
        url = item["URL"]
    except Exception:
        url = ""

    return derive_thumbnail_url(url) or ""


# Context processor to inject theme into all templates
@app.context_processor
def inject_theme():
    # If user is logged in, fetch their theme preference
    if "user_id" in session:
        try:
            s = db.get_user_settings(session["user_id"])
            return {"theme": s["Theme"] or "light"}
        except Exception:
            pass
    # Default theme if not logged in or error occurs
    return {"theme": "light"}


# Home route
# Redirects user based on login status
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# Sign Up / Register Route
# Handles user registration
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        try:
            username = validate_username(username)
            password = validate_password(password)
        except ValidationError as err:
            return render_template("signup.html", error=err.message)

        # Hash password before storing
        password_hash = generate_password_hash(password)

        # Attempt to create user
        try:
            db.create_user(username, password_hash)
        except sqlite3.IntegrityError:
            return render_template("signup.html", error = "Username already exists")

        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


# Login Route
# Authenticates user and creates session
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # Retrieve user from database
        user = db.get_user_by_username(username)

        # Validate password
        if user and check_password_hash(user["PasswordHash"], password):
            session["user_id"] = user["UserID"]
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


# Logout Route
# Removes user session
@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


# Dashboard Route
# Displays all saved content for the logged-in user
@app.route("/dashboard", methods=["GET"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Fetch content and categories
    content = db.get_all_content(user_id)
    categories = db.get_categories(user_id)

    return render_template("dashboard.html", content=content, categories=categories)


# Helper function to resolve category ID
# Prioritises new category creation over existing selection
def _parse_category_id(user_id, raw_id, new_category_name):
    if new_category_name:
        existing = db.get_category_by_name(user_id, new_category_name)

        # Return existing category if found
        if existing:
            return existing["CategoryID"]

        # Create new category if not found
        try:
            return db.create_category(user_id, new_category_name.strip())
        except sqlite3.IntegrityError:
            existing = db.get_category_by_name(user_id, new_category_name)
            return existing["CategoryID"] if existing else None

    # Handle existing category selection
    if raw_id:
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            return None

        row = db.get_category_by_id(cid, user_id)
        return row["CategoryID"] if row else None

    return None


@app.route("/api/content_preview", methods=["POST"])
def content_preview(): # Return metadata title for URL so UI can prefill title 
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    payload = request.get_json(silent=True) or {} # parses the JSON body sent from the front end 
    url_raw = payload.get("url", "") # Extracts the URL field 

    try:
        url = validate_url(url_raw) # calls a function from validator.py to check if URL is valid 
    except ValidationError as err:
        return jsonify({"ok": False, "error": err.message}), 400

    try:
        from Services.metadata import fetch_metadata

        meta = fetch_metadata(url, os.environ.get("YOUTUBE_API_KEY")) or {} # calls the title from the URL or API key
    except Exception as ex:
        logger.warning("content_preview metadata fetch failed: %s", ex)
        meta = {}

    return jsonify(
        {
            "ok": True, # indicate sucess
            "title": (meta.get("title") or "").strip(), # uses metadta title stripped of whitespace
        }
    )


# Add Content Route
# Handles adding new saved content
@app.route("/add_content", methods=["GET", "POST"])
def add_content():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Prevent direct GET access
    if request.method == "GET":
        return redirect(url_for("dashboard"))

    # Extract form data
    url_raw = request.form.get("url", "")
    title = request.form.get("title", "").strip()
    platform = (request.form.get("platform") or "").strip() or None
    notes = (request.form.get("notes") or "").strip() or None
    new_category = (request.form.get("new_category") or "").strip()
    category_id_raw = (request.form.get("category_id") or "").strip()

    try:
        url = validate_url(url_raw)
    except ValidationError as err:
        flash(err.message, "danger")
        return redirect(request.referrer or url_for("dashboard"))

    if db.user_has_saved_url(user_id, url):
        flash("That link is already in your library.", "danger")
        return redirect(request.referrer or url_for("dashboard"))

    # Get user settings (autotagging)
    settings = db.get_user_settings(user_id)
    autotagging = bool(settings["AutoTagging"])

    thumbnail = None
    description = None
    meta = None

    # Always fetch metadata so video thumbnails (e.g. YouTube) are saved, autotagging adds tags/categories only
    try:
        from Services.metadata import fetch_metadata

        meta = fetch_metadata(url, os.environ.get("YOUTUBE_API_KEY"))

        thumbnail = meta.get("thumbnail")
        description = meta.get("description")

        if not platform and meta.get("platform"):
            platform = meta.get("platform")

        if not title and meta.get("title"):
            title = meta.get("title")

    except Exception as ex:
        logger.warning("Metadata fetch failed: %s", ex)

    # Default title fallback
    if not title:
        title = "Untitled"

    # Resolve category
    category_id = _parse_category_id(user_id, category_id_raw, new_category)

    # Auto-categorisation if enabled
    if autotagging and category_id is None and not new_category:
        try:
            from Services.categoriser import categorise

            cat_name = categorise(title, description)

            existing = db.get_category_by_name(user_id, cat_name)

            category_id = (
                existing["CategoryID"]
                if existing
                else db.create_category(user_id, cat_name)
            )

        except Exception as ex:
            logger.warning("Auto-categorise failed: %s", ex)

    # Insert content into database
    try:
        content_id = db.create_content(
            user_id, url, title, platform, notes, thumbnail, category_id
        )
    except Exception as ex:
        logger.exception("create_content failed: %s", ex)
        flash("Could not save content.", "danger")
        return redirect(url_for("dashboard"))

    # Auto-tagging process
    if autotagging and content_id:
        try:
            from Services.categoriser import generate_tags

            tags = generate_tags(title, description, max_tags=5)

            for tag_name in tags:
                tid = db.get_or_create_tag(user_id, tag_name)
                db.add_tag_to_content(content_id, tid)

        except Exception as ex:
            logger.warning("Auto-tags failed: %s", ex)

    flash("Content saved.", "success")
    return redirect(url_for("dashboard"))


# Content Library Route
# Displays all saved content in library view
@app.route("/content_library", methods=["GET"])
def content_library():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    content = db.get_all_content(user_id)
    categories = db.get_categories(user_id)

    return render_template("content_library.html", content=content, categories=categories)


# Content Detail Route
# Displays a single content item and its tags
@app.route("/content_detail/<int:content_id>", methods=["GET"])
def content_detail(content_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Fetch content securely for that user
    content = db.fetch_one(
        "SELECT * FROM Content WHERE ContentID = ? AND UserID = ? AND IsDeleted = 0",
        (content_id, user_id),
    )

    if not content:
        return render_template("404.html"), 404

    # Fetch associated tags
    tags = db.get_tags_for_content(content_id)

    return render_template("content_detail.html", content=content, tags=tags)


# Edit Content Route
# Allows user to update existing content
@app.route("/edit_content/<int:content_id>", methods=["GET", "POST"])
def edit_content(content_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Fetch content
    content = db.fetch_one(
        "SELECT * FROM Content WHERE ContentID = ? AND UserID = ? AND IsDeleted = 0",
        (content_id, user_id),
    )

    if not content:
        return render_template("404.html"), 404

    # Handle form submission
    if request.method == "POST":
        title = request.form["title"]
        notes = request.form["notes"]
        new_category = (request.form.get("new_category") or "").strip()
        category_id_raw = (request.form.get("category_id") or "").strip()

        cid = _parse_category_id(user_id, category_id_raw, new_category)

        db.update_content(content_id, user_id, title, notes, cid)

        return redirect(url_for("content_detail", content_id=content_id))

    categories = db.get_categories(user_id)

    current_category_name = ""
    if content["CategoryID"]:
        cat_row = db.get_category_by_id(content["CategoryID"], user_id)
        if cat_row:
            current_category_name = cat_row["CategoryName"] or ""

    return render_template(
        "edit_content.html",
        content=content,
        categories=categories,
        current_category_name=current_category_name,
    )


# Delete Content Route
# Soft deletes a content item
@app.route("/delete_content/<int:content_id>", methods=["POST"])
def delete_content(content_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    db.delete_content(content_id, user_id)

    return redirect(url_for("dashboard"))


# Clear Library Route
# Deletes all content for a user
@app.route("/clear_library", methods=["POST"])
def clear_library():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db.delete_all_content_for_user(session["user_id"])

    flash("All saved content has been removed from your library.", "info")

    return redirect(url_for("content_library"))


# Delete Account Route
# Permanently deletes user account after confirmation
@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_delete", "").strip()

    user = db.get_user_by_id(user_id)

    # Validate password
    if not user or not check_password_hash(user["PasswordHash"], password):
        flash("Incorrect password.", "danger")
        return redirect(url_for("setting_screen"))

    # Require DELETE confirmation
    if confirm != "DELETE":
        flash('Type the word DELETE to confirm account removal.', "danger")
        return redirect(url_for("setting_screen"))

    # Delete user and clear session
    db.delete_user(user_id)
    session.clear()

    flash("Your account has been permanently deleted.", "info")

    return redirect(url_for("login"))


# Settings Route
# Allows user to update preferences
@app.route("/setting_screen", methods=["GET", "POST"])
def setting_screen():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Handle settings update
    if request.method == "POST":
        theme = request.form.get("theme", "light").strip().lower()

        # Validate theme
        if theme not in {"light", "dark"}:
            theme = "light"

        autotagging = 1 if request.form.get("autotagging") == "1" else 0

        current = db.get_user_settings(user_id)

        db.update_user(
            user_id,
            theme,
            autotagging,
            current["ClearLibraryOnDelete"],
            current["AccountDeletionConfirm"],
        )

        flash("Settings saved.", "success")

        return redirect(url_for("setting_screen"))

    settings = db.get_user_settings(user_id)

    return render_template("settings.html", settings=settings)


# 404 Error Handler
# Displays custom page when route not found
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


# 500 Error Handler
# Displays custom page for server errors
@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500


# Run the application
if __name__ == "__main__":
    app.run(debug=True)