-- Enable foreign key constraints
PRAGMA foreign_keys = ON;
-- Users table to store user accounts
CREATE TABLE IF NOT EXISTS Users (
    UserID INTEGER PRIMARY KEY AUTOINCREMENT,
    Username TEXT NOT NULL UNIQUE,
    PasswordHash TEXT NOT NULL
);
-- Categories table to store user-specific categories
CREATE TABLE IF NOT EXISTS Categories (
    CategoryID INTEGER PRIMARY KEY AUTOINCREMENT,
    UserID INTEGER NOT NULL,
    CategoryName TEXT NOT NULL,
    UNIQUE (UserID, CategoryName),
    FOREIGN KEY (UserID) REFERENCES Users (UserID) ON DELETE CASCADE
);

-- Tags table to store user-specific tags
CREATE TABLE IF NOT EXISTS Tags (
    TagID INTEGER PRIMARY KEY AUTOINCREMENT,
    UserID INTEGER NOT NULL,
    TagName TEXT NOT NULL,
    UNIQUE (UserID, TagName),
    FOREIGN KEY (UserID) REFERENCES Users (UserID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS Content (
    ContentID INTEGER PRIMARY KEY AUTOINCREMENT,
    UserID INTEGER NOT NULL,
    URL TEXT NOT NULL,
    Title TEXT NOT NULL,
    Platform TEXT,
    Notes TEXT,
    Thumbnail TEXT,
    CategoryID INTEGER,
    DateSaved TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    IsDeleted INTEGER NOT NULL DEFAULT 0 CHECK (IsDeleted IN (0, 1)),
    FOREIGN KEY (UserID) REFERENCES Users (UserID) ON DELETE CASCADE,
    FOREIGN KEY (CategoryID) REFERENCES Categories (CategoryID) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ContentTags (
    ContentID INTEGER NOT NULL,
    TagID INTEGER NOT NULL,
    PRIMARY KEY (ContentID, TagID),
    FOREIGN KEY (ContentID) REFERENCES Content (ContentID) ON DELETE CASCADE, -- Cascade delete if content is deleted
    FOREIGN KEY (TagID) REFERENCES Tags (TagID) ON DELETE CASCADE -- Cascade delete if tag is deleted
);

-- User settings table to store per-user preferences (I added it because before it wasnt saving user preferences )
CREATE TABLE IF NOT EXISTS UserSettings (
    UserID INTEGER PRIMARY KEY,
    Theme TEXT NOT NULL DEFAULT 'light',
    AutoTagging INTEGER NOT NULL DEFAULT 1 CHECK (AutoTagging IN (0, 1)), 
    ClearLibraryOnDelete INTEGER NOT NULL DEFAULT 0 CHECK (ClearLibraryOnDelete IN (0, 1)), 
    AccountDeletionConfirm INTEGER NOT NULL DEFAULT 1 CHECK (AccountDeletionConfirm IN (0, 1)),
    FOREIGN KEY (UserID) REFERENCES Users (UserID) ON DELETE CASCADE
);
-- Indexes for common queries which helps improve query performance
CREATE INDEX IF NOT EXISTS idx_content_userid ON Content (UserID);
CREATE INDEX IF NOT EXISTS idx_content_datesaved ON Content (DateSaved);
CREATE INDEX IF NOT EXISTS idx_tags_tagname ON Tags (TagName);
