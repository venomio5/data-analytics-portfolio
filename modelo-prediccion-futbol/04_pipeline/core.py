from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterable, Sequence
import pandas as pd
import numpy as np
from mysql.connector.pooling import MySQLConnectionPool
from datetime import datetime, date, timedelta
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
import webbrowser
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin
from io import StringIO
import requests
from math import radians, sin, cos, sqrt, atan2
import math
from rapidfuzz import process, fuzz
import re
from sklearn.linear_model import Ridge, RidgeCV
from patsy import dmatrix
from patsy import build_design_matrices
import pickle
from scipy import sparse
import json
from tqdm import tqdm
import ast
import xgboost as xgb
import multiprocessing
import os, time, platform, subprocess
from pathlib import Path
import itertools
import copy
import unicodedata
from dotenv import load_dotenv

# ------------------------------ Database Manager ------------------------------
class DatabaseManager:
    """
    Optimizes the initializaiton of a MySQLConnectionPool with UTF-8MB4 encoding.
    """
    def __init__(self,
        host: str,
        user: str,
        password: str,
        database: str,
        port: int = 3306,
        pool_name: str = "db_pool",
        pool_size: int = 6,
    ) -> None:
        self._pool: MySQLConnectionPool = MySQLConnectionPool(
            pool_name=pool_name,
            pool_size=pool_size,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            autocommit=False,
        )

    @contextmanager
    def _connection(self):
        conn = self._pool.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _cursor(self, conn):
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def select(self, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
        with self._connection() as conn, self._cursor(conn) as cur:
            cur.execute(sql, params or ())
            columns = [c[0] for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        many: bool = False,
    ) -> int:
        with self._connection() as conn, self._cursor(conn) as cur:
            if many and isinstance(params, Iterable):
                cur.executemany(sql, params)
            else:
                cur.execute(sql, params or ())
            return cur.rowcount

load_dotenv()
host = os.getenv('DB_HOST')
port = int(os.getenv('DB_PORT'))
user = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')
database = os.getenv('DB_NAME')

try:
    DB = DatabaseManager(host=host, user=user, password=password, database=database)
except Exception as e:
    print(f"[INFO] Could not connect to DB: {e}")
    DB = None

# ------------------------------ Scraping Manager ------------------------------
# Chromedriver at https://googlechromelabs.github.io/chrome-for-testing/
class SeleniumManager:
    """
    Manages Chrome driver setup and lifecycle.
    Can optionally re-use a real Chrome profile by launching Chrome
    first with --remote-debugging-port and then attaching Selenium to it.
    """
    def __init__(
        self,
        simple_mode: bool = False,
        use_profile: bool = False,
        profile_name: str = "selenium_chrome_profile",
        port: int = 8989,
        chrome_path: str | None = None,
    ):
        self.simple_mode = simple_mode
        self.use_profile = use_profile
        self.profile_name = profile_name
        self.port = port
        self.chrome_path = chrome_path
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.driver = None
        self.chrome_proc: subprocess.Popen | None = None

    @staticmethod
    def _find_chrome_executable() -> str | None:
        paths = []
        bases = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        ]
        for b in bases:
            paths.extend(
                [
                    os.path.join(b, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(b, "Chromium", "Application", "chrome.exe"),
                ]
            )
        paths.extend(["chrome", "chromium"])

        from shutil import which

        for p in paths:
            if os.sep not in p:
                resolved = which(p)
                if resolved:
                    return resolved
            elif os.path.exists(p):
                return p
        return None

    def _ensure_profile_dir(self) -> str:
        base = Path(__file__).resolve().parent
        profile_dir = base / self.profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        return str(profile_dir)

    def _launch_chrome_with_profile(self, chrome_exec: str, profile_dir: str) -> subprocess.Popen:
        args = [
            chrome_exec,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def __enter__(self):
        # ---------------- external profile ----------------
        if self.use_profile:
            chrome_exec = self.chrome_path or self._find_chrome_executable()
            if not chrome_exec:
                raise RuntimeError("Chrome executable not found. Pass chrome_path or install Chrome.")
            
            profile_dir = self._ensure_profile_dir()
            self.chrome_proc = self._launch_chrome_with_profile(chrome_exec, profile_dir)
            time.sleep(2)

            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.port}")
            self.driver = webdriver.Chrome(options=options)

            return self.driver
        
        # ---------------- no external profile ----------------
        service = Service('chromedriver.exe')
        options = webdriver.ChromeOptions()

        options.page_load_strategy = 'eager'
        if not self.simple_mode:
            performance_args = [
                "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-extensions", "--disable-plugins", "--disable-notifications",
                "--disable-popup-blocking", "--disable-default-apps", "--headless=new",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding", 
                "--disable-client-side-phishing-detection",
                "--blink-settings=imagesEnabled=false",
                "--ignore-certificate-errors",
                "--ignore-ssl-errors",
                f"--user-agent={self.user_agent}"
            ]
        
            for arg in performance_args:
                options.add_argument(arg)

            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_experimental_option("excludeSwitches", ["enable-logging"])
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument("--log-level=3")

        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self.driver

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

        if self.chrome_proc:
            try:
                self.chrome_proc.terminate()
            except Exception:
                pass

# --------------- Useful Functions & Variables ---------------
def get_team_name_by_id(id: int):
    query = "SELECT name FROM teams WHERE id = %s"
    result = DB.select(query, (id,))
    if not result.empty:
        return result.iloc[0]["name"]
    return None

def get_team_id_by_name(team_name: str, league_id: int, match_title: str="") -> int:
    league_result = DB.select("SELECT to_predict, name FROM leagues WHERE id = %s", (league_id,))
    to_predict = bool(league_result.iloc[0]["to_predict"])
    league_name = league_result.iloc[0]["name"]

    if to_predict:
        result = DB.select("SELECT id FROM teams WHERE name = %s AND league_id = %s", (team_name, league_id))
        if not result.empty:
            return int(result.iloc[0]["id"])
        return 1

    non_predict_query = """
        SELECT t.id, l.name AS league_name
        FROM teams t
        JOIN leagues l ON l.id = t.league_id
        WHERE t.name = %s
    """
    result = DB.select(non_predict_query, (team_name,))
    if result.empty:
        return 1

    if len(result) == 1:
        return int(result.iloc[0]["id"])

    print("\n⚠️ Multiple teams found")
    print(f"Match: {match_title}")
    print(f"League: {league_name}")
    print("Select the correct team:\n")

    for idx, row in result.iterrows():
        print(f"{idx + 1}. League: {row['league_name']} (team_id={row['id']})")

    print("0. Unknown / none of the above")

    while True:
        try:
            choice = int(input("\nYour choice: "))
            if choice == 0:
                return 1

            selected_index = choice - 1
            if selected_index in result.index:
                return int(result.loc[selected_index]["id"])

        except ValueError:
            pass

        print("Invalid choice, try again.")

def get_league_name_by_id(league_id: int):
    query = "SELECT name FROM leagues WHERE id = %s"
    result = DB.select(query, (league_id,))
    if not result.empty:
        return result.iloc[0]["name"]
    return None

def match_players(team_id, raw_source):
    if hasattr(raw_source, "toPlainText"):               
        raw_text = raw_source.toPlainText()
        raw_list = [line.strip() for line in raw_text.split("\n")]
    elif isinstance(raw_source, (list, tuple)):         
        raw_list = [str(line).strip() for line in raw_source]
    else:
        raise TypeError("raw_source must be QTextEdit-like or list/tuple")

    clean_list = [l for l in raw_list if l and not any(c.isdigit() for c in l)]

    unmatched_starters = clean_list[:11]
    unmatched_benchers = clean_list[11:]

    player_sql_query = """
        SELECT  player_id,
                SUBSTRING_INDEX(player_id, '_', 1) AS player_name
        FROM    players_data
        WHERE   current_team = %s;
    """
    players_df = DB.select(player_sql_query, (team_id,))

    id_to_name = {row.player_id: preprocess_for_matching(row.player_name)
                  for row in players_df.itertuples(index=False)}
    remaining_ids, remaining_names = list(id_to_name.keys()), list(id_to_name.values())

    def _pick_id(raw_name: str, thr: int):
        norm = _normalize(raw_name)
        match = process.extractOne(norm, remaining_names,
                                   scorer=fuzz.token_set_ratio,
                                   score_cutoff=thr)
        if not match:
            return None
        idx = remaining_names.index(match[0])
        remaining_names.pop(idx) 
        return remaining_ids.pop(idx)

    def _resolve(names):
        out, pending, thr = [], names, 85
        while pending and thr >= 60: 
            still = []
            for n in pending:
                pid = _pick_id(n, thr)
                (out if pid else still).append(pid or n)
            pending, thr = still, thr - 10
        return out

    matched_starters = _resolve(unmatched_starters)
    matched_benchers = _resolve(unmatched_benchers)
    return matched_starters, matched_benchers

def send_lineup_to_db(players_list, match_id, team):
    column_name = f"{team}_players_data"
    sql_query = f"UPDATE schedule SET {column_name} = %s WHERE id = %s"
    DB.execute(sql_query, (json.dumps(players_list, ensure_ascii=False), match_id))

def get_saved_lineup(schedule_id, team):
    column_name = f"{team}_players_data"
    sql_query = f"SELECT {column_name} FROM schedule WHERE id = %s"
    result = DB.select(sql_query, (schedule_id,))

    if result.empty:
        return []

    raw_value = result.iloc[0][column_name]

    if not raw_value:
        return []

    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return []

def get_match_title(id: int):
    sql_query = "SELECT home_team_id, away_team_id FROM schedule WHERE id = %s"
    result = DB.select(sql_query, (id,))

    if not result.empty:
        home_name = get_team_name_by_id(int(result.iloc[0]["home_team_id"]))
        away_name = get_team_name_by_id(int(result.iloc[0]["away_team_id"]))

        return f"{home_name} vs {away_name}"  
    else:
        return id

def flip(series: pd.Series) -> pd.Series:
    flipped = -series
    flipped[series == 0] = 0.0
    return flipped

def get_minutes_strength(teamA_players: list[str], teamB_players: list[str]) -> float:
    def _fetch_minutes(player_ids: list[str]) -> dict[str, int]:
        if not player_ids:
            return {}

        placeholders = ",".join(["%s"] * len(player_ids))
        minutes_query = f"""
            SELECT id, minutes_played
            FROM   players
            WHERE  id IN ({placeholders})
        """
        df = DB.select(minutes_query, tuple(player_ids))
        return dict(zip(df["id"], df["minutes_played"]))

    teamA_minutes = _fetch_minutes(teamA_players)
    teamB_minutes = _fetch_minutes(teamB_players)

    # Calculate average for Team A
    total_A_minutes = 0
    for player in teamA_players:
        total_A_minutes += min(teamA_minutes.get(player, 0) / 1000, 1)
    avg_A = total_A_minutes / len(teamA_players) if teamA_players else 0
    
    # Calculate average for Team B
    total_B_minutes = 0
    for player in teamB_players:
        total_B_minutes += min(teamB_minutes.get(player, 0) / 1000, 1)
    avg_B = total_B_minutes / len(teamB_players) if teamB_players else 0

    return (avg_A + avg_B) / 2

def preprocess_for_matching(text: str, keep_numbers: bool = False) -> str:
    """
    1. Quita acentos
    2. Elimina caracteres no alfanuméricos (opcionalmente mantiene números)
    3. Convierte a minúsculas y colapsa espacios
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    
    if keep_numbers:
        pattern = r"[^a-zA-Z0-9\s]"
    else:
        pattern = r"[^a-zA-Z\s]"
    
    text = re.sub(pattern, " ", text)
    return " ".join(text.lower().split())

def update_players_fatigue_rhythm(home_team_id: int, away_team_id: int, current_date: datetime = datetime.now()):
    """
    Updates players fatigue and rhythm based on their match history.
    """
    date_str = current_date.strftime('%Y-%m-%d %H:%M:%S')

    update_query = f"""
        UPDATE players p
        INNER JOIN (
            SELECT 
                mpb.player_id,
                SUM(mpb.minutes_played * EXP(-DATEDIFF('{date_str}', mg.date) / 3.0)) AS raw_fatigue,
                SUM(mpb.minutes_played * EXP(-DATEDIFF('{date_str}', mg.date) / 7.0)) AS raw_rhythm
            FROM match_player_breakdown mpb
            JOIN match_general mg ON mpb.match_id = mg.id
            JOIN players p ON p.id = mpb.player_id
            WHERE mg.date <= '{date_str}' AND (p.team_id = {home_team_id} OR p.team_id = {away_team_id})
            GROUP BY mpb.player_id
        ) stats ON p.id = stats.player_id
        SET
            p.fatigue = ROUND(LEAST(1, stats.raw_fatigue / 90.0), 3),
            p.rhythm  = ROUND(LEAST(1, stats.raw_rhythm / 90.0), 3)
    """

    DB.execute(update_query)

def load_fr_models():
    with open("Database/fatigue_model.pkl", "rb") as fh:
        fatigue_model = pickle.load(fh)

    with open("Database/rhythm_model.pkl", "rb") as fh:
        rhythm_model = pickle.load(fh)

    return fatigue_model, rhythm_model

def predict_fr_coef(mode: str, coef: float, feature: float, model):
    if mode == "fatigue":
        X = dmatrix(
            "bs(fatigue, df=5, degree=3, include_intercept=False, lower_bound=0.0, upper_bound=1.0)",
            {"fatigue": [feature]},
            return_type="dataframe"
        )

        adjustment = model.predict(X)[0]
        return coef + adjustment
    elif mode == "rhythm":
        X = dmatrix(
            "bs(rhythm, df=5, degree=3, include_intercept=False, lower_bound=0.0, upper_bound=1.0)",
            {"rhythm": [feature]},
            return_type="dataframe"
        )

        adjustment = model.predict(X)[0]
        return coef + adjustment
    else:
        raise ValueError("Invalid mode")

# ------------------------------ Extract & Remove Data ------------------------------
class FillTeamsData:
    """
    Provides a complete refresh of team metadata for a league by scraping and enriching fixture information.  
    Ensures that every team entry in the database reflects accurate, up-to-date details including location and elevation,
    while removing outdated or missing records to maintain data consistency and reliability.
    """
    def __init__(self, league_id):
        self.coordinate_change_threshold = 2.0
        self.league_id = int(league_id)
        league_df = DB.select("SELECT id, fixtures_url FROM leagues WHERE id = %s", (self.league_id,))
        self.league_url = league_df['fixtures_url'].values[0]

        self.existing_teams = self._get_existing_teams()
        teams_venue_data = self._get_teams()
        insert_data = []
        teams_to_manual_check = []

        for team, venue in tqdm(teams_venue_data.items(), desc="Processing teams"):
            existing_coords = self.existing_teams.get(team)
            new_coords = self._get_coordinates(team, venue, existing_coords)

            if new_coords == "manual_input_needed":
                teams_to_manual_check.append((team, venue))
                continue

            lat, lon = new_coords
            coordinates_str = f"{lat},{lon}"
            elevation = self._get_elevation(lat, lon)
            insert_data.append((team, elevation, coordinates_str, self.league_id))

        if teams_to_manual_check:
            print(f"\n⚠️  {len(teams_to_manual_check)} equipos necesitan verificación manual:")
            manual_insert_data = self._process_manual_teams(teams_to_manual_check)
            insert_data.extend(manual_insert_data)

        if insert_data:
            DB.execute(
                """
                INSERT INTO teams (name, elevation, coordinates, league_id)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    elevation = VALUES(elevation),
                    coordinates = VALUES(coordinates)
                """,
                insert_data,
                many=True
            )

        current_team_names = tuple(teams_venue_data.keys())

        if current_team_names:
            placeholders = ','.join(['%s'] * len(current_team_names))
            DB.execute(
                f"""
                DELETE FROM teams
                WHERE league_id = %s AND name NOT IN ({placeholders})
                """,
                (self.league_id, *current_team_names)
            )

    def _process_manual_teams(self, teams_to_manual_check: list) -> list:
            print("\n" + "="*50)
            print("MANUAL FALLBACK MODE (API Failed for these)")
            print("="*50)
            
            manual_insert_data = []
            
            for team, venue in teams_to_manual_check:
                print(f"\n🏟️  Team: {team}")
                print(f"📍 Venue: {venue}")
                
                # Open a search for the venue to help you
                search_query = f"{team} {venue} coordinates"
                webbrowser.open(f"https://www.google.com/search?q={search_query.replace(' ', '+')}")
                
                while True:
                    coords_input = input("   Paste 'lat,lon' (or 's' to skip/keep old): ").strip()
                    
                    if coords_input.lower() == 's':
                        existing = self.existing_teams.get(team)
                        if existing:
                            lat, lon = existing
                            coordinates_str = f"{lat},{lon}"
                            elevation = self._get_elevation(lat, lon)
                            manual_insert_data.append((team, elevation, coordinates_str, self.league_id))
                            print("   ✅ Kept existing data.")
                        else:
                            print("   ⏭️  Skipped (No data saved).")
                        break
                    
                    try:
                        # Allow diverse formats like "12.34, -56.78" or "12.34 -56.78"
                        clean_input = coords_input.replace(' ', '').replace(';', ',')
                        if ',' in clean_input:
                            lat_str, lon_str = clean_input.split(',')
                            lat, lon = float(lat_str), float(lon_str)
                            
                            coordinates_str = f"{lat},{lon}"
                            elevation = self._get_elevation(lat, lon)
                            manual_insert_data.append((team, elevation, coordinates_str, self.league_id))
                            print("   ✅ Saved.")
                            break
                    except ValueError:
                        print("   ❌ Invalid format. Just paste 'lat,lon'.")
            
            return manual_insert_data

    def _get_teams(self) -> dict:
        with SeleniumManager(use_profile=True) as driver:
            driver.get(self.league_url)
            driver.execute_script("window.scrollTo(0, 1000);")

            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.stats_table")))

            soup = BeautifulSoup(driver.page_source, 'html.parser')

        team_venue_map = {}
        rows = soup.select("table.stats_table tbody tr")
        
        for row in rows:
            home_element = row.select_one("[data-stat='home_team'] a")
            if not home_element:
                continue
            
            home = home_element.get_text(strip=True)
            
            if not home or home == "Home":
                continue
            
            venue_element = row.select_one("[data-stat='venue']")
            venue = venue_element.get_text(strip=True) if venue_element else ""
            
            if home not in team_venue_map:
                team_venue_map[home] = venue

        return team_venue_map

    def _get_existing_teams(self) -> dict:
        existing_teams = {}
        result = DB.select("SELECT name, coordinates FROM teams WHERE league_id = %s", (self.league_id,))
        
        for _, row in result.iterrows():
            if row['coordinates']:
                try:
                    lat, lon = map(float, row['coordinates'].split(','))
                    existing_teams[row['name']] = (lat, lon)
                except (ValueError, AttributeError):
                    existing_teams[row['name']] = None
            else:
                existing_teams[row['name']] = None
                
        return existing_teams

    def _calculate_distance(self, coord1: tuple, coord2: tuple) -> float:      
        lat1, lon1 = map(radians, coord1)
        lat2, lon2 = map(radians, coord2)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        radius_earth = 6371 
        
        return radius_earth * c

    def _get_coordinates(self, team: str, place_name: str, existing_coords: tuple) -> tuple:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': place_name,
                'format': 'json',
                'limit': 1
            }
            headers = {
                'User-Agent': 'GeoDataScript/1.0'
            }

            try:
                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

                if data:
                    location = data[0]
                    new_lat = float(location['lat'])
                    new_lon = float(location['lon'])
                    
                    print(f"\n📍 {team}: {location['display_name']}")
                    
                    # --- CASE 1: New Team (No existing data) ---
                    if not existing_coords:
                        print("   ✨ New team detected. Auto-accepting coordinates.")
                        return new_lat, new_lon

                    # --- CASE 2: Existing Team (Check distance) ---
                    distance = self._calculate_distance(existing_coords, (new_lat, new_lon))
                    
                    if distance <= self.coordinate_change_threshold:
                        print(f"   ✅ Verified (Diff: {distance:.2f} km)")
                        return new_lat, new_lon
                    else:
                        # --- CASE 3: Significant Change (Conflict) ---
                        print(f"   ⚠️  Significant change: {distance:.2f} km")
                        print(f"   Old: {existing_coords[0]:.6f}, {existing_coords[1]:.6f}")
                        print(f"   New: {new_lat:.6f}, {new_lon:.6f} (Opening map...)")
                        
                        # Open the NEW coordinates so you can verify if the new scrape is correct
                        webbrowser.open(f"https://www.google.com/maps?q={new_lat},{new_lon}")
                        
                        while True:
                            confirm = input("   Update to NEW coordinates? (y/n): ").strip().lower()
                            if confirm == 'y':
                                return new_lat, new_lon
                            elif confirm == 'n':
                                print("   🔙 Keeping OLD coordinates.")
                                return existing_coords
                
                else:
                    print(f"\n❌ {team}: Location '{place_name}' not found by API.")
                    return "manual_input_needed"
            
            except Exception as e:
                print(f"Error getting coordinates for {team}: {e}")
            
            return "manual_input_needed"

    def _get_elevation(self, latitude: float, longitude: float) -> int:
        try:
            url = "https://api.open-elevation.com/api/v1/lookup"
            params = {"locations": f"{latitude},{longitude}"}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'results' in data and data['results']:
                elevation_meters = data['results'][0]['elevation']
                return int(elevation_meters)
            else:
                raise ValueError("No elevation data returned from Open-Elevation")
                
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            print(f"Open-Elevation failed: {e}. Trying Open Topo Data...")
        
        try:
            url = "https://api.opentopodata.org/v1/srtm30m"
            params = {"locations": f"{latitude},{longitude}"}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'results' in data and data['results']:
                elevation_meters = data['results'][0]['elevation']
                return int(elevation_meters)
            else:
                raise ValueError("No elevation data returned from Open Topo Data")
                
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            raise ValueError(f"Both elevation APIs failed. Last error: {e}")

class ScrapeMatchesData:
    """
    Scrapes and extracts data from matches froom fbref and saves them into the database
    """
    def __init__(self, to_date: str, simulate: bool=False, backtesting: bool=False):
        self.to_date = datetime.strptime(to_date, '%Y-%m-%d').date()
        self.simulate = simulate
        self.base_url = "https://fbref.com"
        if not backtesting:
            self._update_recent_games_match_general_data()
        self._update_matches_data()
        self._update_fatigue_rhythm()
        self._set_fr_rag()
        self._set_raw_ras()
        self._remove_old_data()

    def _update_recent_games_match_general_data(self):
        active_leagues_df = DB.select("SELECT * FROM leagues WHERE is_active = 1")

        insert_match_data_query = """
        INSERT IGNORE INTO match_general (
            home_team_id, away_team_id, date, league_id, url
        ) VALUES (%s, %s, %s, %s, %s)
        """
        update_league_lud_query = "UPDATE leagues SET last_updated_date = %s WHERE id = %s"

        pbar = tqdm(active_leagues_df["id"].tolist(), desc="Processing leagues", unit="league")
        for league_id in pbar:
            pbar.set_postfix({"league": get_league_name_by_id(league_id)})
            url = active_leagues_df[active_leagues_df['id'] == league_id]['fixtures_url'].values[0]
            lud = active_leagues_df[active_leagues_df['id'] == league_id]['last_updated_date'].values[0]
            game_urls, game_dates, game_times, home_teams, away_teams  = self._get_matches_basic_data(url, lud)

            batch_params = []
            for i in tqdm(range(len(game_urls)), desc="Saving matches data"):
                game_url = game_urls[i]
                game_date = game_dates[i]
                game_time = game_times[i]
                game_datetime = datetime.combine(game_date, game_time)
                home_team = home_teams[i]
                home_id = get_team_id_by_name(home_team, league_id, f"{home_teams[i]} vs {away_teams[i]}")
                away_team = away_teams[i]
                away_id = get_team_id_by_name(away_team, league_id, f"{home_teams[i]} vs {away_teams[i]}") 

                if home_id == 1 and away_id == 1:
                    continue

                batch_params.append((
                    home_id,
                    away_id,
                    game_datetime,
                    league_id,
                    game_url,
                ))
            if batch_params:
                DB.execute(insert_match_data_query, batch_params, many=True)
            
            DB.execute(update_league_lud_query, (self.to_date, league_id))
        pbar.close()

    def _get_matches_basic_data(self, url: str, lud: date) -> tuple[list, list, list, list, list]:
        with SeleniumManager(use_profile=True) as driver:
            driver.get(url)
            driver.execute_script("window.scrollTo(0, 3000);")

            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.stats_table")))

            soup = BeautifulSoup(driver.page_source, 'html.parser')

        rows = soup.select("table.stats_table tbody tr")

        game_data = []
        for row in rows:
            try:
                date_el = row.select_one("[data-stat='date']")
                home_el = row.select_one("[data-stat='home_team']")
                away_el = row.select_one("[data-stat='away_team']")
                time_el = row.select_one(".venuetime")
                url_el = row.select_one("[data-stat='match_report'] a")
                
                if not date_el or not home_el or not away_el or not url_el:
                    continue
                
                date_text = date_el.get_text(strip=True)
                
                home_a = home_el.select_one('a')
                home = home_a.get_text(strip=True) if home_a else home_el.get_text(strip=True)

                away_a = away_el.select_one('a')
                away = away_a.get_text(strip=True) if away_a else away_el.get_text(strip=True)
                time_text = time_el.get_text(strip=True) if time_el else ""
                game_url = urljoin(self.base_url, url_el.get('href', '').strip())
                
                date_text_clean = re.sub(r'[^0-9-]', '', date_text)
                if not date_text_clean:
                    continue
                
                game_date = datetime.strptime(date_text_clean, '%Y-%m-%d').date()
                
                if not (lud <= game_date <= self.to_date):
                    continue
                
                venue_time_obj = None
                if time_text:
                    time_clean = time_text.strip("()")
                    try:
                        venue_time_obj = datetime.strptime(time_clean, "%H:%M").time()
                    except ValueError:
                        continue
                
                if not game_url:
                    continue
                
                game_data.append((game_url, game_date, venue_time_obj, home, away))
                
            except Exception as e:
                print("Exception in row ", e)
                continue
        
        if game_data:
            return zip(*game_data)
        else:
            return ([], [], [], [], [])

    def _update_matches_data(self) -> None:
        """
        Get the matches_id, that are missing data, to update them for the player breakdown and detailed tables
        """
        general = DB.select("""
            SELECT mg.id, mg.url, mg.home_team_id, mg.away_team_id, mg.date, l.to_predict
            FROM match_general mg
            JOIN leagues l ON l.id = mg.league_id
        """)
        general["date"] = pd.to_datetime(general["date"])
        cutoff_date = pd.Timestamp(self.to_date)
        general = general[general["date"] < cutoff_date]
        player_ids = set(DB.select("SELECT match_id FROM match_player_breakdown")["match_id"])
        missing = general[~general["id"].isin(player_ids)]

        with SeleniumManager(use_profile=True) as driver:
            pbar = tqdm(missing.iterrows(), total=len(missing), desc="Processing Matches", unit="match")
            
            for _, row in pbar:
                pbar.set_postfix({"match": row['id']})

                driver.get(row['url'])
                driver.execute_script("window.scrollTo(0, 1000);")
                WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".table_container")))

                try:
                    switchers = driver.find_elements(By.CSS_SELECTOR, ".filter.switcher")
                    for switcher in switchers:
                        links = switcher.find_elements(By.TAG_NAME, "a")
                        for link in links:
                            if "Miscellaneous Stats" in link.get_attribute("innerHTML"):
                                driver.execute_script("arguments[0].click();", link)
                    
                    WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".table_container.tabbed.current")))
                except:
                    pass

                html = driver.execute_script("return document.body.innerHTML")
                soup = BeautifulSoup(html, "html.parser")

                home_team_id    = row['home_team_id']
                away_team_id    = row['away_team_id']
                home_team       = get_team_name_by_id(home_team_id)
                away_team       = get_team_name_by_id(away_team_id)
                match_id        = row["id"]

                # Lineups
                home_players = []
                away_players = []
                is_predict_league = bool(row["to_predict"])

                try:
                    h_table_html = str(soup.select_one('#a table'))
                    a_table_html = str(soup.select_one('#b table'))
                    home_data = pd.read_html(StringIO(h_table_html))[0]
                    away_data = pd.read_html(StringIO(a_table_html))[0]

                    home_players = self._extract_players(home_data, home_team)
                    away_players = self._extract_players(away_data, away_team)
                except Exception as e:
                    print(f"Error parsing lineups: {e}")
                    is_predict_league = False

                    # Fallback: Extract players from stats tables
                    tabbed_tables = soup.select(".table_wrapper.tabbed") + soup.select(".table_wrapper")
                    
                    for table in tabbed_tables:
                        heading = table.select_one(".section_heading")
                        heading_text = heading.get_text().strip() if heading else ""
                        
                        target_list = None
                        target_initials = ""

                        if home_team in heading_text:
                            target_list = home_players
                            target_initials = ''.join(word[0].upper() for word in home_team.split() if word)
                        elif away_team in heading_text:
                            target_list = away_players
                            target_initials = ''.join(word[0].upper() for word in away_team.split() if word)
                        
                        if target_list is None:
                            continue

                        stats_table = table.select_one(".stats_table")
                        if not stats_table: continue
                        
                        tbody = stats_table.select_one("tbody")
                        if not tbody: continue

                        for r in tbody.select("tr"):
                            player_th = r.select_one('[data-stat="player"]')
                            if not player_th or player_th.get_text().strip() == "Player":
                                continue
                            
                            name = player_th.get_text().strip()
                            n_el = r.select_one('[data-stat="shirtnumber"]')
                            number = n_el.get_text().strip() if n_el else "0"
                            
                            pid = f"{name}_{number}_{target_initials}"
                            if pid not in target_list:
                                target_list.append(pid)

                if is_predict_league:
                    if self.simulate:
                        sch_id = self._get_sch_id(home_id=home_team_id, away_id=away_team_id, date=row["date"])
                        home_players_data = self._build_player_dicts(home_players)
                        away_players_data = self._build_player_dicts(away_players)
                        send_lineup_to_db(home_players_data, match_id=sch_id, team="home")
                        send_lineup_to_db(away_players_data, match_id=sch_id, team="away")

                    # Events
                    events_wrap = soup.select_one('#events_wrap')
                    if not events_wrap:
                        continue

                    subs_events = []
                    goal_events = []
                    red_events = []
                    extra_first_half = 0
                    extra_second_half = 0

                    for event in events_wrap.select('.event'):
                        text_content = event.get_text(separator="\n").strip()
                        lines = text_content.split('\n')
                        event_minute = None

                        for line in lines:
                            m = re.match(r'^\s*(\d+)(?:\+(\d+))?’.?$', line)
                            if m:
                                base_minute = int(m.group(1))
                                plus = m.group(2)
                                if base_minute == 45 and plus:
                                    extra_first_half = max(extra_first_half, int(plus))
                                if base_minute == 90 and plus:
                                    extra_second_half = max(extra_second_half, int(plus))
                                event_minute = base_minute if not plus else base_minute + int(plus)
                                break

                        if event_minute is None:
                            continue

                        classes = event.get('class', [])
                        team = "home" if "a" in classes else "away" if "b" in classes else None
                        if team is None:
                            continue

                        if event.select('[class*="substitute_in"]'):
                            player_out, player_in = None, None

                            player_links = event.select('a')
                            if len(player_links) >= 2:
                                player_in = player_links[0].get_text().strip()
                                player_out = player_links[1].get_text().strip()
                            
                            if player_out and player_in:
                                subs_events.append((event_minute, player_out, player_in, team))

                        if event.select('[class*="goal"]'):
                            goal_events.append((event_minute, team))

                        if event.select('[class*="red_card"]'):
                            player_links = event.select('a')
                            if player_links:
                                player_name = player_links[0].get_text().strip()
                                red_events.append((event_minute, player_name, team))

                    # Shots
                    shots_table_tag = soup.select_one('#shots_all')
                    if not shots_table_tag:
                        print(f"Deleting {row['id']}")
                        DB.execute("DELETE FROM match_general WHERE id = %s", (match_id,))
                        continue

                    shots_df = pd.read_html(StringIO(str(shots_table_tag)))[0]
                    shots_df.columns = pd.MultiIndex.from_tuples(shots_df.columns)
                    selected_columns = shots_df.loc[:, [('Unnamed: 0_level_0', 'Minute'),
                                                        ('Unnamed: 2_level_0', 'Squad'),
                                                        ('Unnamed: 3_level_0', 'xG')]]
                    cleaned_columns = []
                    for col in selected_columns.columns:
                        if 'Unnamed' in col[0]:
                            cleaned_columns.append(col[1])
                        else:
                            cleaned_columns.append('_'.join(col).strip())
                    selected_columns.columns = cleaned_columns
                    selected_columns = selected_columns[selected_columns['Minute'].notna() & (selected_columns['Minute'] != 'Minute')]

                    shot_minutes_info = []
                    for minute_str in selected_columns['Minute'].astype(str):
                        if '+' in minute_str:
                            base, extra = minute_str.split('+')
                            base = int(float(base))
                            extra = int(float(extra)) if extra else 0
                        else:
                            base = int(float(minute_str))
                            extra = 0
                        shot_minutes_info.append((base, extra))

                    max_extra_first_half_shots = max((extra for base, extra in shot_minutes_info if base == 45), default=0)
                    max_extra_second_half_shots = max((extra for base, extra in shot_minutes_info if base == 90), default=0)

                    extra_first_half = max(extra_first_half, max_extra_first_half_shots)
                    extra_second_half = max(extra_second_half, max_extra_second_half_shots)
                
                    def _parse_minute(minute_str):
                        try:
                            if '+' in str(minute_str):
                                parts = str(minute_str).split('+')
                                return float(parts[0]) + float(parts[1])
                            else:
                                return float(minute_str)
                        except:
                            return float(minute_str)
                    
                    selected_columns['Minute'] = selected_columns['Minute'].astype(str).apply(_parse_minute)
                    selected_columns['xG'] = selected_columns['xG'].astype(float)

                    # Minute Adjustments
                    total_minutes = 90 + extra_first_half + extra_second_half

                    def adjust_minute(minute, extra_first_half):
                        if minute > 45:
                            return minute + extra_first_half
                        return minute

                    selected_columns['Adjusted_Minute'] = selected_columns['Minute'].apply(lambda x: adjust_minute(x, extra_first_half))

                    adjusted_subs_events = []
                    for minute, player_out, player_in, team in subs_events:
                        adjusted_minute = adjust_minute(minute, extra_first_half)
                        adjusted_subs_events.append((adjusted_minute, player_out, player_in, team))

                    adjusted_goal_events = []
                    for minute, team in goal_events:
                        adjusted_minute = adjust_minute(minute, extra_first_half)
                        adjusted_goal_events.append((adjusted_minute, team))

                    adjusted_red_events = []
                    for minute, player_name, team in red_events:
                        adjusted_minute = adjust_minute(minute, extra_first_half)
                        adjusted_red_events.append((adjusted_minute, player_name, team))

                    event_minutes = [se[0] for se in adjusted_subs_events] + [ge[0] for ge in adjusted_goal_events] + [re[0] for re in adjusted_red_events]
                    time_segment_boundaries = [0, 15, 30, 45 + extra_first_half, 60 + extra_first_half, 75 + extra_first_half, total_minutes]

                    # Segments
                    boundaries = sorted(set(event_minutes) | set(time_segment_boundaries) | {0, total_minutes})

                    for seg_start, seg_end in zip(boundaries, boundaries[1:]):
                        time_segment = min(int(seg_start // 15) + 1, 6)

                        seg_duration = seg_end - seg_start
                        if seg_duration == 0: continue

                        teamA_lineup = self._get_lineups(home_players, adjusted_subs_events, seg_start, "home", adjusted_red_events)
                        teamB_lineup = self._get_lineups(away_players, adjusted_subs_events, seg_start, "away", adjusted_red_events)
                        minutes_strength = get_minutes_strength(teamA_lineup, teamB_lineup)

                        seg_shots = selected_columns[(selected_columns['Adjusted_Minute'] > seg_start) & (selected_columns['Adjusted_Minute'] <= seg_end)]
                        teamA_xg = 0.0
                        teamB_xg = 0.0
                        teamA_sh = 0
                        teamB_sh = 0
                        for _, seg_row in seg_shots.iterrows():
                            if home_team in seg_row['Squad']:
                                teamA_xg += seg_row['xG']
                                teamA_sh += 1
                            elif away_team in seg_row['Squad']:
                                teamB_xg += seg_row['xG']
                                teamB_sh += 1

                        cum_goal_home = sum(1 for minute, t in adjusted_goal_events if minute < seg_end and t == "home")
                        cum_goal_away = sum(1 for minute, t in adjusted_goal_events if minute < seg_end and t == "away")

                        goal_diff = cum_goal_home - cum_goal_away
                        if goal_diff == 0:
                            match_state = "0"
                        elif goal_diff == 1:
                            match_state = "0.5"
                        elif goal_diff > 1:
                            match_state = "1.5"
                        elif goal_diff == -1:
                            match_state = "-0.5"
                        else:
                            match_state = "-1.5"

                        cum_red_home = sum(1 for minute, _, t in adjusted_red_events if minute < seg_end and t == "home")
                        cum_red_away = sum(1 for minute, _, t in adjusted_red_events if minute < seg_end and t == "away")
                        red_diff = cum_red_away - cum_red_home
                        if red_diff == 0:
                            player_dif = "0"
                        elif red_diff == 1:
                            player_dif = "0.5"
                        elif red_diff > 1:
                            player_dif = "1.5"
                        elif red_diff == -1:
                            player_dif = "-0.5"
                        else:
                            player_dif = "-1.5"

                        insert_detailed_query = """
                        INSERT IGNORE INTO match_detailed (
                            match_id, 
                            teamA_players, 
                            teamB_players, 
                            teamA_xg, 
                            teamB_xg, 
                            teamA_sh,
                            teamB_sh,
                            time_segment,
                            minutes_played, 
                            match_state, 
                            player_dif,
                            minutes_strength
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        params = (
                            match_id, 
                            json.dumps(teamA_lineup, sort_keys=True), 
                            json.dumps(teamB_lineup, sort_keys=True), 
                            teamA_xg, 
                            teamB_xg, 
                            teamA_sh,
                            teamB_sh,
                            time_segment,
                            seg_duration, 
                            match_state, 
                            player_dif, 
                            minutes_strength
                        ) 
                        DB.execute(insert_detailed_query, params)

                    # Player breakdown
                    home_player_stats = self._initialize_player_stats(home_players)
                    away_player_stats = self._initialize_player_stats(away_players)

                    for sub_event in adjusted_subs_events:
                        sub_minute, player_out, player_in, sub_team = sub_event

                        h_goals_now = sum(1 for minute, t in goal_events if t == "home" and minute <= sub_minute)
                        a_goals_now = sum(1 for minute, t in goal_events if t == "away" and minute <= sub_minute)
                        
                        if sub_team == "home":
                            team_stats = home_player_stats
                            state = "leading" if h_goals_now > a_goals_now else "level" if h_goals_now == a_goals_now else "trailing"
                        else:
                            team_stats = away_player_stats
                            state = "leading" if a_goals_now > h_goals_now else "level" if a_goals_now == h_goals_now else "trailing"

                        for key in team_stats:
                            if key.split("_")[0] == player_out:
                                team_stats[key]["sub_out_min"] = sub_minute
                                team_stats[key]["out_status"] = state

                        found_in = False
                        for key in team_stats:
                            if key.split("_")[0] == player_in:
                                team_stats[key]["sub_in_min"] = sub_minute
                                team_stats[key]["in_status"] = state
                                found_in = True
                        
                        if not found_in:
                            new_stats = self._initialize_player_stats([player_in])
                            new_stats[player_in]["starter"] = False
                            new_stats[player_in]["sub_in_min"] = sub_minute
                            new_stats[player_in]["in_status"] = state
                            new_stats[player_in]["sub_out_min"] = None
                            team_stats.update(new_stats)

                    for team_stats in (home_player_stats, away_player_stats):
                        for key, stat in list(team_stats.items()):
                            stat.setdefault("starter", True)
                            stat.setdefault("sub_in_min",  None)
                            stat.setdefault("sub_out_min", None)
                            stat.setdefault("in_status",   None)
                            stat.setdefault("out_status",  None)

                            if not stat["starter"] and stat["sub_in_min"] is None:
                                stat["minutes_played"] = 0
                                continue

                            in_min  = 0 if stat["starter"] else stat["sub_in_min"]
                            out_min = stat["sub_out_min"] if stat["sub_out_min"] is not None else total_minutes
                            out_min = min(out_min, total_minutes)

                            calculated_minutes = out_min - (in_min if in_min is not None else 0)
                            stat["minutes_played"] = max(0, calculated_minutes)

                    tabbed_tables = soup.select(".table_wrapper.tabbed")

                    for table in tabbed_tables:
                        heading = table.select_one(".section_heading")
                        heading_text = heading.get_text().strip() if heading else ""

                        if home_team in heading_text:
                            is_home_table = True
                            target_stats = home_player_stats
                        elif away_team in heading_text:
                            is_home_table = False
                            target_stats = away_player_stats
                        else:
                            continue

                        clean_heading = heading_text
                        if "Player Stats" in heading_text:
                            clean_heading = heading_text[:heading_text.find("Player Stats")].strip()
                        team_initials = ''.join(word[0].upper() for word in clean_heading.split() if word)

                        stats_table = table.select_one(".table_container.tabbed.current .stats_table")
                        if not stats_table:
                            stats_table = table.select_one(".stats_table")

                        if stats_table:
                            tbody = stats_table.select_one("tbody")
                            if not tbody: continue

                            rows = tbody.select("tr")
                            for row in rows:
                                try:
                                    def get_stat(r, stat_name):
                                        el = r.select_one(f'[data-stat="{stat_name}"]')
                                        return el.get_text().strip() if el else "0"
                                    
                                    player_name = get_stat(row, "player")
                                    shirt_number = get_stat(row, "shirtnumber")
                                    
                                    if player_name == "Player": continue

                                    fouls_committed = int(get_stat(row, "fouls")) if get_stat(row, "fouls").isdigit() else 0
                                    fouls_drawn = int(get_stat(row, "fouled")) if get_stat(row, "fouled").isdigit() else 0
                                    yellow = int(get_stat(row, "cards_yellow")) if get_stat(row, "cards_yellow").isdigit() else 0
                                    red = int(get_stat(row, "cards_red")) if get_stat(row, "cards_red").isdigit() else 0

                                    player_key = f"{player_name}_{shirt_number}_{team_initials}"
                                    
                                    target_stats = None
                                    if player_key in home_player_stats:
                                        target_stats = home_player_stats
                                    elif player_key in away_player_stats:
                                        target_stats = away_player_stats
                                    
                                    if target_stats:
                                        target_stats[player_key]["fouls_committed"] = fouls_committed
                                        target_stats[player_key]["fouls_drawn"] = fouls_drawn
                                        target_stats[player_key]["yellow_cards"] = yellow
                                        target_stats[player_key]["red_cards"] = red

                                except Exception as e:
                                    continue

                    insert_sql = "INSERT IGNORE INTO match_player_breakdown (match_id, player_id, sub_in, sub_out, in_status, out_status, fouls_committed, fouls_drawn, yellow_cards, red_cards, minutes_played) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"

                    for team_stats in (home_player_stats, away_player_stats):
                        for player, stat in team_stats.items():
                            if stat.get("sub_out_min", 0) == 0:
                                continue
                            params = (match_id,
                                    stat["id"],
                                    stat["sub_in_min"],
                                    stat["sub_out_min"],
                                    stat["in_status"],
                                    stat["out_status"],
                                    stat.get("fouls_committed", 0),
                                    stat.get("fouls_drawn", 0),
                                    stat.get("yellow_cards", 0),
                                    stat.get("red_cards", 0),
                                    stat["minutes_played"])
                            DB.execute(insert_sql, params)
                elif not is_predict_league:
                    # Player breakdown
                    home_player_stats = self._initialize_player_stats(home_players)
                    away_player_stats = self._initialize_player_stats(away_players)

                    tabbed_tables = soup.select(".table_wrapper.tabbed")

                    for table in tabbed_tables:
                        heading = table.select_one(".section_heading")
                        heading_text = heading.get_text().strip() if heading else ""

                        if home_team in heading_text:
                            is_home_table = True
                            target_stats = home_player_stats
                        elif away_team in heading_text:
                            is_home_table = False
                            target_stats = away_player_stats
                        else:
                            continue

                        clean_heading = heading_text
                        if "Player Stats" in heading_text:
                            clean_heading = heading_text[:heading_text.find("Player Stats")].strip()
                        team_initials = ''.join(word[0].upper() for word in clean_heading.split() if word)

                        stats_table = table.select_one(".table_container.tabbed.current .stats_table")
                        if not stats_table:
                            stats_table = table.select_one(".stats_table")

                        if stats_table:
                            tbody = stats_table.select_one("tbody")
                            if not tbody: continue

                            rows = tbody.select("tr")
                            for row in rows:
                                try:
                                    def get_stat(r, stat_name):
                                        el = r.select_one(f'[data-stat="{stat_name}"]')
                                        return el.get_text().strip() if el else "0"
                                    
                                    player_name = get_stat(row, "player")
                                    shirt_number = get_stat(row, "shirtnumber")
                                    
                                    if player_name == "Player": continue

                                    minutes_played = int(get_stat(row, "minutes")) if get_stat(row, "minutes").isdigit() else 0
                                    fouls_committed = int(get_stat(row, "fouls")) if get_stat(row, "fouls").isdigit() else 0
                                    fouls_drawn = int(get_stat(row, "fouled")) if get_stat(row, "fouled").isdigit() else 0
                                    yellow = int(get_stat(row, "cards_yellow")) if get_stat(row, "cards_yellow").isdigit() else 0
                                    red = int(get_stat(row, "cards_red")) if get_stat(row, "cards_red").isdigit() else 0

                                    player_key = f"{player_name}_{shirt_number}_{team_initials}"
                                    
                                    target_stats = None
                                    if player_key in home_player_stats:
                                        target_stats = home_player_stats
                                    elif player_key in away_player_stats:
                                        target_stats = away_player_stats
                                    
                                    if target_stats:
                                        target_stats[player_key]["minutes_played"] = minutes_played
                                        target_stats[player_key]["fouls_committed"] = fouls_committed
                                        target_stats[player_key]["fouls_drawn"] = fouls_drawn
                                        target_stats[player_key]["yellow_cards"] = yellow
                                        target_stats[player_key]["red_cards"] = red

                                except Exception as e:
                                    continue

                    insert_sql = "INSERT IGNORE INTO match_player_breakdown (match_id, player_id, fouls_committed, fouls_drawn, yellow_cards, red_cards, minutes_played) VALUES (%s, %s, %s, %s, %s, %s, %s)"

                    teams_to_insert = []

                    if home_team_id != 1:
                        teams_to_insert.append(home_player_stats)

                    if away_team_id != 1:
                        teams_to_insert.append(away_player_stats)

                    for team_stats in teams_to_insert:
                        for player, stat in team_stats.items():
                            params = (match_id,
                                    stat["id"],
                                    stat.get("fouls_committed", 0),
                                    stat.get("fouls_drawn", 0),
                                    stat.get("yellow_cards", 0),
                                    stat.get("red_cards", 0),
                                    stat.get("minutes_played", 0))
                            DB.execute(insert_sql, params)
            pbar.close()
    
    def _get_sch_id(self, home_id: int, away_id: int, date: datetime) -> int:
        sch_query = """
            SELECT id
            FROM schedule 
            WHERE home_team_id = %s 
            AND away_team_id = %s 
            AND date = %s
        """

        sch_df = DB.select(sch_query, (home_id, away_id, date.date()))

        if not sch_df.empty:
            return int(sch_df.iloc[0]['id'])
        else:
            return None

    def _extract_players(self, df, team_name: str) -> list[str]:
        team_initials = ''.join(word[0].upper() for word in team_name.split() if word)

        col_name = df.columns[1]
        filtered = df[~df[col_name].str.contains("Bench", na=False)]

        players = [f"{row[col_name]}_{row.iloc[0]}_{team_initials}" for _, row in filtered.iterrows()]

        return players

    def _initialize_player_stats(self, players: list) -> dict[str, dict[str, Any]]:
        return {
            player: {
                "id": player,
                "starter": i < 11,
            } for i, player in enumerate(players)
        }

    def _get_lineups(self, initial_players: list, sub_events: list, current_minute: int, team: str, red_events=None) -> list[str]:
        if red_events is None:
            red_events = []
        
        roster_mapping = {}
        for player in initial_players:
            key = player.split("_")[0]
            roster_mapping[key] = player

        lineup = initial_players[:11]

        filtered_subs = [s for s in sub_events if s[3] == team]
        filtered_subs = sorted(filtered_subs, key=lambda x: x[0])

        for sub_minute, player_out, player_in, _ in filtered_subs:
            if sub_minute > current_minute:
                break

            for idx, player in enumerate(lineup):
                if player.split("_")[0] == player_out:
                    replacement = roster_mapping.get(player_in, player_in)
                    lineup[idx] = replacement
                    roster_mapping[player_in] = replacement
                    break

        sent_off = [p for m, p, t in red_events if t == team and m <= current_minute]
        lineup = [p for p in lineup if p.split("_")[0] not in sent_off]

        lineup = [roster_mapping.get(p.split("_")[0], p) for p in lineup]
        return lineup

    def _build_player_dicts(self, players: list[str]) -> dict:
        player_dicts = []

        for i, player_id in enumerate(players):
            if i < 11:
                player_dicts.append({
                    'player_id': player_id,
                    'yellow_card': False,
                    'red_card': False,
                    'on_field': True,
                    'bench': False
                })
            else:
                player_dicts.append({
                    'player_id': player_id,
                    'yellow_card': False,
                    'red_card': False,
                    'on_field': False,
                    'bench': True
                })
        
        return player_dicts

    def _update_fatigue_rhythm(self):
        """
        Updates fatigue and rhythm db
        """

        all_detailed = DB.select(
            """
            SELECT DISTINCT md.match_id
            FROM vsp.match_detailed md
            JOIN vsp.match_general mg ON mg.id = md.match_id
            WHERE mg.date BETWEEN DATE_SUB(%s, INTERVAL 3 DAY) AND %s
            AND md.minutes_strength > 0.7
            """,
            params=(self.to_date, self.to_date)
        )
        processed_stats = DB.select("SELECT DISTINCT match_id FROM vsp.player_fatigue_rhythm")
        
        detailed_ids = set(all_detailed["match_id"])
        processed_ids = set(processed_stats["match_id"])
        
        missing_ids = list(detailed_ids - processed_ids)

        if not missing_ids:
            print("No new matches to process.")
            return

        players_df = DB.select("SELECT id, off_xg_coef, def_xg_coef, fatigue, rhythm FROM players")
        player_lookup = {
                row['id']: {
                    'off': row['off_xg_coef'] or 0,
                    'def': row['def_xg_coef'] or 0,
                    'fatigue': row['fatigue'] or 0,
                    'rhythm': row['rhythm'] or 0
                } for _, row in players_df.iterrows()
            }

        placeholders = ', '.join(['%s'] * len(missing_ids))
        matches_sql = f"""
            SELECT 
                mg.id AS match_id, 
                DATE(mg.date) AS date,
                mg.league_id,
                md.teamA_players, md.teamB_players,
                SUM(md.minutes_played) AS minutes_played,
                SUM(md.teamA_xg) AS teamA_xg,
                SUM(md.teamB_xg) AS teamB_xg
            FROM vsp.match_general mg
            JOIN vsp.match_detailed md ON md.match_id = mg.id
            WHERE mg.id IN ({placeholders})
            AND mg.date BETWEEN DATE_SUB(%s, INTERVAL 3 DAY) AND %s
            AND md.minutes_strength > 0.7
            GROUP BY mg.id, mg.date, mg.league_id, md.teamA_players, md.teamB_players
        """
        matches_df = DB.select(matches_sql, params=missing_ids + [self.to_date, self.to_date])

        matches_df['teamA_players'] = matches_df['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
        matches_df['teamB_players'] = matches_df['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))

        league_ids = matches_df['league_id'].unique().tolist()

        baselines_raw = DB.select(
            f"SELECT id, rag_baseline FROM leagues WHERE id IN ({','.join(['%s']*len(league_ids))})", 
            tuple(league_ids)
        )
        baseline_map = dict(zip(baselines_raw['id'], baselines_raw['rag_baseline']))

        insert_payload = []

        for _, match in tqdm(matches_df.iterrows(), total=len(matches_df)):
            m_id = match['match_id']
            m_date = match['date']
            mins = int(match['minutes_played'])
            
            if mins <= 10: continue

            teamA_pids = [p for p in match['teamA_players'] if p]
            teamB_pids = [p for p in match['teamB_players'] if p]

            if len(teamA_pids) != 11 or len(teamB_pids) != 11: continue

            rag_baseline_coef = float(baseline_map.get(match['league_id'], 0.0))     

            self._process_perspective(insert_payload, m_id, mins, teamA_pids, teamB_pids, 
                                match['teamA_xg'], match['teamB_xg'], player_lookup, rag_baseline_coef)
            
            self._process_perspective(insert_payload, m_id, mins, teamB_pids, teamA_pids, 
                                match['teamB_xg'], match['teamA_xg'], player_lookup, rag_baseline_coef)

        if insert_payload:
            sql_insert = """
                INSERT IGNORE INTO player_fatigue_rhythm 
                (match_id, player_id, fatigue, rhythm, 
                r_adjustment, f_adjustment)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            rows_affected = DB.execute(sql_insert, params=insert_payload, many=True)
            print(f"Successfully inserted {rows_affected} player-match records.")

    def _process_perspective(self, payload, m_id, mins, t_pids, o_pids, t_xg, o_xg, lookup, league_baseline):
        """
        Allocates real match xG to players using ADDITIVE allocation (Surplus/Deficit distribution)
        to handle negative coefficients correctly.
        """
        base_vol_per_player = (league_baseline * mins) / 22

        team_off_sum = sum(lookup.get(p, {}).get('off', 0) for p in t_pids)
        opp_def_sum = sum(lookup.get(p, {}).get('def', 0) for p in o_pids)
        
        team_projected_total = (league_baseline + team_off_sum - opp_def_sum) * mins

        off_surplus = t_xg - team_projected_total
        off_surplus_per_player = off_surplus / 22

        opp_off_sum = sum(lookup.get(p, {}).get('off', 0) for p in o_pids)
        team_def_sum = sum(lookup.get(p, {}).get('def', 0) for p in t_pids)
        
        opp_projected_total = (league_baseline + opp_off_sum - team_def_sum) * mins
        
        def_surplus = opp_projected_total - o_xg
        def_surplus_per_player = def_surplus / 22

        team_fatigues = [lookup.get(pid, {}).get('fatigue', 0) for pid in t_pids]
        team_rhythms = [lookup.get(pid, {}).get('rhythm', 0) for pid in t_pids]

        avg_team_fatigue = sum(team_fatigues) / len(team_fatigues) if team_fatigues else 0
        avg_team_rhythm = sum(team_rhythms) / len(team_rhythms) if team_rhythms else 0

        tolerance = 0.10

        for pid in t_pids:
            p = lookup.get(pid, {'off': 0, 'def': 0, 'fatigue': 0, 'rhythm': 0})

            is_fatigue_outlier = abs(p['fatigue'] - avg_team_fatigue) > tolerance
            is_rhythm_outlier = abs(p['rhythm'] - avg_team_rhythm) > tolerance

            if is_fatigue_outlier or is_rhythm_outlier:
                continue
            
            player_proj_off = base_vol_per_player + (p['off'] * mins)
            player_real_off_xg = player_proj_off + off_surplus_per_player

            player_proj_def = base_vol_per_player + (p['def'] * mins)
            player_real_def_xg = player_proj_def + def_surplus_per_player

            clean_real_off_vol = (player_real_off_xg - base_vol_per_player) / mins
            clean_real_def_vol = (base_vol_per_player - player_real_def_xg) / mins

            r_adjustment = clean_real_off_vol - p['off']
            f_adjustment = clean_real_def_vol - p['def']

            payload.append((
                m_id, 
                pid, 
                p['fatigue'], 
                p['rhythm'],           
                r_adjustment,          
                f_adjustment
            ))

    def _set_fr_rag(self):
        """
        Updating fatigue & rhythm RAG for past matches
        """
        fatigue_model, rhythm_model = load_fr_models()

        non_fr_rag_matches_query = """
            SELECT 
                md.id,
                md.match_id,
                mg.league_id,
                md.teamA_players,
                md.teamB_players,
                md.minutes_played
            FROM match_detailed md
            JOIN match_general mg
                ON mg.id = md.match_id
            WHERE (md.teamA_fr_rag IS NULL OR md.teamB_fr_rag IS NULL)
            AND mg.date <= %s
            AND mg.date >= "2024-01-01"
        """
        non_fr_rag_matches_df = DB.select(non_fr_rag_matches_query, (self.to_date,))

        if non_fr_rag_matches_df.empty:
            return

        non_fr_rag_matches_df['teamA_players'] = non_fr_rag_matches_df['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
        non_fr_rag_matches_df['teamB_players'] = non_fr_rag_matches_df['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))

        active_players = set()
        for _, row in non_fr_rag_matches_df.iterrows():
            active_players.update(row['teamA_players'])
            active_players.update(row['teamB_players'])

        if not active_players:
            return

        placeholders = ','.join(['%s'] * len(active_players))
        players_sql = f"""
            SELECT id, off_xg_coef, def_xg_coef, fatigue, rhythm
            FROM players
            WHERE id IN ({placeholders});
        """
        active_players_df = DB.select(players_sql, list(active_players))
        player_lookup = {
            row['id']: {
                'fr_xg_off_coef': predict_fr_coef(
                    mode="rhythm",
                    coef=row['off_xg_coef'] if pd.notna(row['off_xg_coef']) else 0,
                    feature=row['rhythm'] if pd.notna(row['rhythm']) else 0,
                    model=rhythm_model
                ),
                'fr_xg_def_coef': predict_fr_coef(
                    mode="fatigue",
                    coef=row['def_xg_coef'] if pd.notna(row['def_xg_coef']) else 0,
                    feature=row['fatigue'] if pd.notna(row['fatigue']) else 0,
                    model=fatigue_model
                )
            }
            for _, row in active_players_df.iterrows()
        }

        league_df = DB.select("SELECT id, rag_baseline FROM leagues")
        baseline_dict = league_df.set_index("id")["rag_baseline"].to_dict()

        for _, row in tqdm(non_fr_rag_matches_df.iterrows(), total=len(non_fr_rag_matches_df), desc="Processing Non-FR-RAG Matches", unit="match"):
            minutes = int(row['minutes_played'])
            league_id = row['league_id']
            baseline = baseline_dict.get(league_id, 0.0)

            teamA_pids = [p for p in row['teamA_players'] if p]
            teamB_pids = [p for p in row['teamB_players'] if p]

            teamA_off_sum = sum(player_lookup.get(p, {}).get('fr_xg_off_coef', 0) for p in teamA_pids)
            teamB_def_sum = sum(player_lookup.get(p, {}).get('fr_xg_def_coef', 0) for p in teamB_pids)
            
            teamA_fr_rag = (baseline + teamA_off_sum - teamB_def_sum) * minutes

            teamB_off_sum = sum(player_lookup.get(p, {}).get('fr_xg_off_coef', 0) for p in teamB_pids)
            teamA_def_sum = sum(player_lookup.get(p, {}).get('fr_xg_def_coef', 0) for p in teamA_pids)
            
            teamB_fr_rag = (baseline + teamB_off_sum - teamA_def_sum) * minutes

            DB.execute("UPDATE match_detailed SET teamA_fr_rag = %s, teamB_fr_rag = %s WHERE id = %s", (teamA_fr_rag, teamB_fr_rag, row['id']))

    def _set_raw_ras(self):
        """
        Updating raw RAS for past matches
        """
        non_raw_ras_matches_query = """
            SELECT 
                md.id,
                md.match_id,
                mg.league_id,
                md.teamA_players,
                md.teamB_players,
                md.minutes_played
            FROM match_detailed md
            JOIN match_general mg
                ON mg.id = md.match_id
            WHERE (md.teamA_raw_ras IS NULL OR md.teamB_raw_ras IS NULL)
            AND mg.date <= %s
            AND mg.date >= "2022-01-01"
        """
        non_raw_ras_matches_df = DB.select(non_raw_ras_matches_query, (self.to_date,))

        if non_raw_ras_matches_df.empty:
            return

        non_raw_ras_matches_df['teamA_players'] = non_raw_ras_matches_df['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
        non_raw_ras_matches_df['teamB_players'] = non_raw_ras_matches_df['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))

        active_players = set()
        for _, row in non_raw_ras_matches_df.iterrows():
            active_players.update(row['teamA_players'])
            active_players.update(row['teamB_players'])

        if not active_players:
            return

        placeholders = ','.join(['%s'] * len(active_players))
        players_sql = f"""
            SELECT id, off_sh_coef, def_sh_coef
            FROM players
            WHERE id IN ({placeholders});
        """
        active_players_df = DB.select(players_sql, list(active_players))
        player_lookup = {
            row['id']: {
                'off_sh_coef': row['off_sh_coef'],
                'def_sh_coef': row['def_sh_coef']
            }
            for _, row in active_players_df.iterrows()
        }

        league_df = DB.select("SELECT id, ras_baseline FROM leagues")
        baseline_dict = league_df.set_index("id")["ras_baseline"].to_dict()

        for _, row in tqdm(non_raw_ras_matches_df.iterrows(), total=len(non_raw_ras_matches_df), desc="Processing Non-Raw-RAS Matches", unit="match"):
            minutes = int(row['minutes_played'])
            league_id = row['league_id']
            baseline = baseline_dict.get(league_id, 0.0)

            teamA_pids = [p for p in row['teamA_players'] if p]
            teamB_pids = [p for p in row['teamB_players'] if p]

            teamA_off_sum = sum(player_lookup.get(p, {}).get('off_sh_coef', 0) for p in teamA_pids)
            teamB_def_sum = sum(player_lookup.get(p, {}).get('def_sh_coef', 0) for p in teamB_pids)
            
            teamA_raw_ras = (baseline + teamA_off_sum - teamB_def_sum) * minutes

            teamB_off_sum = sum(player_lookup.get(p, {}).get('off_sh_coef', 0) for p in teamB_pids)
            teamA_def_sum = sum(player_lookup.get(p, {}).get('def_sh_coef', 0) for p in teamA_pids)
            
            teamB_raw_ras = (baseline + teamB_off_sum - teamA_def_sum) * minutes

            DB.execute("UPDATE match_detailed SET teamA_raw_ras = %s, teamB_raw_ras = %s WHERE id = %s", (teamA_raw_ras, teamB_raw_ras, row['id']))

    def _remove_old_data(self):
        self.last_date = self.to_date - timedelta(days=1000)

        delete_query  = """
        DELETE FROM match_general 
        WHERE date < %s
        """

        DB.execute(delete_query, (self.last_date,))

class UpdateSchedule:
    """
    Update the info for next matches. And updates the general table data if match is there.
    """
    def __init__(self, from_date: date, to_date: date, backtesting: bool = False, only_transfers: bool = False):
        self.from_date = from_date
        self.to_date = to_date
        self.backtesting = backtesting
        self.only_transfers = only_transfers

        active_leagues_df = DB.select("SELECT * FROM leagues WHERE is_active = 1")

        pbar = tqdm(active_leagues_df["id"].tolist(), desc="Processing leagues", unit="league")
        for league_id in pbar:
            pbar.set_postfix({"league": get_league_name_by_id(league_id)})
            if not self.only_transfers:
                league_df = DB.select("SELECT to_predict FROM leagues WHERE id = %s", (league_id,))
                to_predict = league_df.iloc[0]['to_predict'] if not league_df.empty else 0
                fixtures_url = active_leagues_df[active_leagues_df['id'] == league_id]['fixtures_url'].values[0]
                
                game_urls, game_dates, game_times, home_teams, away_teams = self._get_matches_basic_data(fixtures_url)
                
                if self.backtesting:
                    insert_match_data_query = """
                    INSERT IGNORE INTO match_general (
                        home_team_id, away_team_id, date, league_id, url
                    ) VALUES (%s, %s, %s, %s, %s)
                    """
                    match_params = []
                
                for i in tqdm(range(len(game_dates)), desc="Saving matches data"):
                    game_date = game_dates[i]
                    game_time = game_times[i]

                    home_team = home_teams[i]
                    home_id = get_team_id_by_name(home_team, league_id)
                    away_team = away_teams[i]
                    away_id = get_team_id_by_name(away_team, league_id)

                    if home_id == 1 or away_id == 1 or to_predict != 1: 
                        home_elevation_dif = 0
                        away_elevation_dif = 0
                        away_travel_dist = 0
                    else:
                        home_elevation_dif, away_elevation_dif = self._get_elevation_dif(home_id, away_id, league_id)
                        away_travel_dist = self._get_travel_distance(home_id, away_id)

                    insert_query = """
                    INSERT INTO schedule (
                        home_team_id,
                        away_team_id,
                        date,
                        local_time,
                        league_id,
                        home_elevation_dif,
                        away_elevation_dif,
                        away_travel
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        local_time   = VALUES(local_time)
                    """

                    raw_params = (
                        home_id,
                        away_id,
                        game_date,
                        game_time,
                        league_id,
                        home_elevation_dif,
                        away_elevation_dif,
                        away_travel_dist
                    )

                    DB.execute(insert_query, raw_params)

                    if self.backtesting:
                        match_params.append((
                            home_id,
                            away_id,
                            datetime.combine(game_date, game_time),
                            league_id,
                            game_urls[i]
                        ))

                if self.backtesting and match_params:
                    DB.execute(insert_match_data_query, match_params, many=True)

            transfer_query = """
            UPDATE match_general mg
            JOIN schedule s
                ON mg.home_team_id = s.home_team_id
                AND mg.away_team_id = s.away_team_id
                AND DATE(mg.date) = s.date
                AND mg.league_id   = s.league_id
            SET mg.home_elevation_dif = s.home_elevation_dif,
                mg.away_elevation_dif = s.away_elevation_dif,
                mg.away_travel        = s.away_travel
            WHERE s.date < %s
            AND s.league_id = %s
            """
            DB.execute(transfer_query, (self.from_date, league_id))

            delete_query = """
            DELETE s
            FROM schedule s
            JOIN match_general mg
                ON mg.home_team_id = s.home_team_id
                AND mg.away_team_id = s.away_team_id
                AND DATE(mg.date) = s.date
                AND mg.league_id = s.league_id
            WHERE s.date < %s
            AND s.league_id = %s
            """
            DB.execute(delete_query, (self.from_date, league_id))
            
            cutoff_date = self.from_date - timedelta(days=30)
            
            stale_delete_sql = """
            DELETE s
            FROM schedule s
            WHERE s.date < %s
            AND s.league_id = %s
            """
            DB.execute(stale_delete_sql, (cutoff_date, league_id))
        pbar.close()

    def _get_matches_basic_data(self, url: str) -> tuple[list, list, list, list, list]:
        with SeleniumManager(use_profile=True) as driver:
            driver.get(url)
            driver.execute_script("window.scrollTo(0, 1000);")

            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.stats_table")))
            page_source = driver.page_source

        soup = BeautifulSoup(page_source, "html.parser")
        rows = soup.select("table.stats_table tbody tr")

        game_urls = []
        game_dates = []
        game_times = []
        home_teams = []
        away_teams = []

        for row in rows:
            date_element = row.select_one("[data-stat='date']")

            if not date_element:
                continue

            date_text = date_element.get_text(strip=True)
            cleaned_date_text = re.sub(r"[^0-9-]", "", date_text)

            if not cleaned_date_text:
                continue

            try:
                game_date = datetime.strptime(cleaned_date_text, "%Y-%m-%d").date()

                if self.from_date <= game_date <= self.to_date:
                    venue_time_element = row.select_one(".venuetime")
 
                    if venue_time_element:
                        venue_time_str = venue_time_element.get_text(strip=True).strip("()")
                        venue_time_obj = datetime.strptime(venue_time_str, "%H:%M").time()
                    else:
                        venue_time_obj = time(0, 0)

                    if self.backtesting:
                        url_element = row.select_one("[data-stat='match_report'] a")
                        game_url = urljoin("https://fbref.com", url_element.get('href', '').strip())
                        game_urls.append(game_url)
                    else:
                        game_urls.append(None)

                    home_el = row.select_one("[data-stat='home_team']")
                    home_a = home_el.select_one('a')
                    home_name = home_a.get_text(strip=True) if home_a else home_el.get_text(strip=True)

                    away_el = row.select_one("[data-stat='away_team']")
                    away_a = away_el.select_one('a')
                    away_name = away_a.get_text(strip=True) if away_a else away_el.get_text(strip=True)

                    game_dates.append(game_date)
                    game_times.append(venue_time_obj)
                    home_teams.append(home_name)
                    away_teams.append(away_name)
            except Exception:
                continue

        return game_urls, game_dates, game_times, home_teams, away_teams

    def _get_elevation_dif(self, home_id: int, away_id: int, league_id: int) -> tuple[int, int]:
        teams_df = DB.select("SELECT * FROM teams WHERE league_id = %s", (league_id,))

        home_team = teams_df[teams_df["id"] == home_id].iloc[0]
        away_team = teams_df[teams_df["id"] == away_id].iloc[0]

        league_elevation_avg = teams_df["elevation"].mean()

        home_elevation = home_team["elevation"]
        away_elevation = away_team["elevation"]

        home_reference_avg = (league_elevation_avg + home_elevation) / 2
        away_reference_avg = (league_elevation_avg + away_elevation) / 2

        home_elevation_difference = round(home_elevation - home_reference_avg)
        away_elevation_difference = round(away_elevation - away_reference_avg)
        return home_elevation_difference, away_elevation_difference

    def _get_travel_distance(self, home_id: int, away_id: int) -> int:
        teams_df = DB.select(f"SELECT * FROM teams WHERE id IN ({home_id}, {away_id})")

        home_team = teams_df[teams_df["id"] == home_id].iloc[0]
        away_team = teams_df[teams_df["id"] == away_id].iloc[0]

        lat1, lon1 = map(str.strip, home_team["coordinates"].split(','))
        lat2, lon2 = map(str.strip, away_team["coordinates"].split(','))
    
        lat1_rad = math.radians(float(lat1))
        lon1_rad = math.radians(float(lon1))
        lat2_rad = math.radians(float(lat2))
        lon2_rad = math.radians(float(lon2))

        R = 6371.0

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        distance = int(round(R * c))
        
        return distance

# ------------------------------ Process Data ------------------------------
class ProcessData:
    """
    Trains models and updates data
    """
    def __init__(self, current_date: datetime = datetime.now(), simulation: bool = False):
        self.current_date = current_date
        # steps = []
        DB.execute("TRUNCATE TABLE players")

        steps = [
            ("Inserting players basics and unifying duplicates", self._insert_players_basics),
            ("Training raw RAG", self._train_raw_rag),
            ("Training raw RAS", self._train_raw_ras),
            ("Updating players totals", self._update_players_totals),
            ("Training fatigue & rhythm model", self._train_fatigue_rhythm_model)
        ]

        if simulation:
            steps.extend([
                ("Updating reg totals", self._update_reg_totals),
                ("Training contextual RAS model", self._train_contextual_ras_model),
                ("Training contextual RAG model", self._train_contextual_rag_model)
            ])
        
        for desc, step_func in tqdm(steps, desc="Progress", unit="step"):
            print(desc)
            step_func()

    def _insert_players_basics(self):
        """
        Inserts players name and current team id. Then runs a function to unify duplicated players.
        """
        sql_query = """
        SELECT md.teamA_players, md.teamB_players, mg.home_team_id, mg.away_team_id 
        FROM match_detailed md
        JOIN match_general mg
            ON md.match_id = mg.id
        WHERE DATE(mg.date) < %s
        """
        result = DB.select(sql_query, (self.current_date,))
        
        if result.empty:
            return 0
        
        result['teamA_players'] = result['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
        result['teamB_players'] = result['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))

        players_set = set()
        for _, row in result.iterrows():
            teamA_players = row['teamA_players'] if isinstance(row['teamA_players'], list) else [row['teamA_players']]
            teamB_players = row['teamB_players'] if isinstance(row['teamB_players'], list) else [row['teamB_players']]
            home_team = int(row["home_team_id"])
            away_team = int(row["away_team_id"])
        
            for player in teamA_players:
                players_set.add((player, home_team))
            
            for player in teamB_players:
                players_set.add((player, away_team))
        
        insert_sql = "INSERT IGNORE INTO players (id, team_id) VALUES (%s, %s)"
        DB.execute(insert_sql, list(players_set), many=True)

        self._unify_duplicated_players()

    def _unify_duplicated_players(self):
        """
        This function consolidates duplicate player records by:
        1. Grouping player IDs by their team and name (disregarding jersey number).
        2. Identifying groups where IDs never appear together in the same match—these are considered the same player.
        3. For each group:
            • Selecting the most recent ID as the canonical one.
            • Updating all other database tables to reference this canonical ID.
            • Deleting the obsolete player IDs from the master player table.
        """
        _ID_RE = re.compile(r"(?P<name>.+?)_\d+_[A-Z]{1,2}$")
        df = DB.select("SELECT id, team_id FROM players")
        groups = {}
        for pid, team in df[["id", "team_id"]].itertuples(index=False):
            m = _ID_RE.match(pid)
            if not m:
                continue
            key = (team, m.group("name").strip().lower())
            groups.setdefault(key, []).append(pid)
        
        for (team, _), ids in tqdm(groups.items(), desc="Group of players to unify"):
            if len(ids) < 2:
                continue
            
            if self._appear_together(ids):
                continue

            keep_id  = self._most_recent_id(ids)

            obsolete = [i for i in ids if i != keep_id]

            self._rewrite_ids(obsolete, keep_id)

            if obsolete:
                ph = ",".join(["%s"] * len(obsolete))
                DB.execute(f"DELETE FROM players WHERE id IN ({ph})", tuple(obsolete),)

    def _appear_together(self, ids):
        ors = []
        params = []

        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                ors.append(
                "("
                "(JSON_CONTAINS(teamA_players, %s) AND JSON_CONTAINS(teamA_players, %s)) OR "
                "(JSON_CONTAINS(teamB_players, %s) AND JSON_CONTAINS(teamB_players, %s))"
                ")"
                )
                params.extend([json.dumps(a), json.dumps(b), json.dumps(a), json.dumps(b)])
        sql = "SELECT 1 FROM match_detailed WHERE " + " OR ".join(ors) + " LIMIT 1"
        return not DB.select(sql, params).empty

    def _most_recent_id(self, ids):
        most_recent   = None
        latest_game   = -1

        for pid in ids:
            sql = """
            SELECT MAX(match_id) AS last_game
            FROM   match_detailed
            WHERE  JSON_CONTAINS(teamA_players, JSON_QUOTE(%s), '$')
               OR  JSON_CONTAINS(teamB_players, JSON_QUOTE(%s), '$')
            """
            res = DB.select(sql, (pid, pid))
            last = res.iloc[0]["last_game"] if not res.empty else None
            if last is not None and last > latest_game:
                latest_game = last
                most_recent = pid

        return most_recent or sorted(ids)[-1]

    def _rewrite_ids(self, olds, new):
        # ---------- match_detailed ----------
        cond_parts = []
        params = []
        for o in olds:
            cond_parts.append(
                "(JSON_CONTAINS(teamA_players, JSON_QUOTE(%s), '$') "
                " OR JSON_CONTAINS(teamB_players, JSON_QUOTE(%s), '$'))"
            )
            params.extend([o, o])

        cond = " OR ".join(cond_parts)

        sql = f"""
            SELECT match_id, teamA_players, teamB_players
            FROM match_detailed
            WHERE {cond}
        """

        rows = DB.select(sql, params)

        for _, r in rows.iterrows():
            a = json.dumps([new if p in olds else p for p in json.loads(r["teamA_players"])])
            b = json.dumps([new if p in olds else p for p in json.loads(r["teamB_players"])])
            DB.execute("UPDATE match_detailed SET teamA_players=%s, teamB_players=%s WHERE match_id=%s",(a, b, r["match_id"]),)

        # ---------- match_player_breakdown ----------
        for o in olds:
            DB.execute("UPDATE IGNORE match_player_breakdown ""SET player_id = %s ""WHERE player_id = %s",(new, o),)
            DB.execute("DELETE FROM match_player_breakdown WHERE player_id = %s",(o,),)

    def _train_raw_rag(self):
        """
        A ridge regression (linear model) that learns individual players offensive and defensive impact. 
        Having more weight on recent matches, for up to matches for the preceding year.
        It updates players coefficients per league
        """
        leagues_df = DB.select("SELECT id FROM leagues WHERE is_active = 1 AND to_predict = 1")

        for lid in tqdm(leagues_df['id'].tolist(), desc="League RAG Coeff", unit="league"):
            matches_query = """
            SELECT 
                mg.id, 
                mg.date,
                md.teamA_players, 
                md.teamB_players, 
                md.teamA_xg,
                md.teamB_xg,
                md.minutes_played
            FROM match_general mg
            JOIN match_detailed md
                ON mg.id = md.match_id
            WHERE league_id = %s
            AND DATE(mg.date) < %s
            """
            matches_df = DB.select(matches_query, (lid, self.current_date))

            if matches_df.empty:
                continue 

            matches_df['date'] = pd.to_datetime(matches_df['date'])
            matches_df['days_ago'] = (self.current_date - matches_df['date']).dt.days

            matches_df['teamA_players'] = matches_df['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
            matches_df['teamB_players'] = matches_df['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
            matches_df['time_weight'] = np.exp(-np.log(2) * matches_df['days_ago'] / 180)
            total_weight = matches_df['time_weight'].sum()
            matches_df['time_weight'] = matches_df['time_weight'] / total_weight * len(matches_df)

            players_set = set()
            for idx, row in matches_df.iterrows():
                teamA = row['teamA_players'] if isinstance(row['teamA_players'], list) else [row['teamA_players']]
                teamB = row['teamB_players'] if isinstance(row['teamB_players'], list) else [row['teamB_players']]
                players_set.update(teamA)
                players_set.update(teamB)

            players = sorted(list(players_set))
            num_players = len(players)
            players_to_index = {player: idx for idx, player in enumerate(players)}

            rows = []
            cols = []
            data_vals = []
            y = []
            sample_weights = []
            row_num = 0

            for idx, row in matches_df.iterrows():
                minutes = int(row['minutes_played'])
                if minutes == 0:
                    continue
                
                time_weight = float(row['time_weight'])
                teamA_players = row['teamA_players'] if isinstance(row['teamA_players'], list) else [row['teamA_players']]
                teamB_players = row['teamB_players'] if isinstance(row['teamB_players'], list) else [row['teamB_players']]
                teamA_xg = float(row['teamA_xg'])
                teamB_xg = float(row['teamB_xg'])

                # Team A's offensive possessions (positive for offense, negative for defense)
                for p in teamA_players:
                    rows.append(row_num)
                    cols.append(players_to_index[p])
                    data_vals.append(1)
                for p in teamB_players:
                    rows.append(row_num)
                    cols.append(num_players + players_to_index[p])
                    data_vals.append(-1)
                y.append(teamA_xg / minutes)
                sample_weights.append(np.sqrt(minutes * time_weight))
                row_num += 1

                # Team B's offensive possessions
                for p in teamB_players:
                    rows.append(row_num)
                    cols.append(players_to_index[p])
                    data_vals.append(1)
                for p in teamA_players:
                    rows.append(row_num)
                    cols.append(num_players + players_to_index[p])
                    data_vals.append(-1)
                y.append(teamB_xg / minutes)
                sample_weights.append(np.sqrt(minutes * time_weight))
                row_num += 1

            X = sparse.csr_matrix((data_vals, (rows, cols)), shape=(row_num, 2 * num_players))
            y_array = np.array(y)
            sample_weights_array = np.array(sample_weights)

            y_mean = np.average(y_array, weights=sample_weights_array)
            y_centered = y_array - y_mean


            alphas = np.logspace(-3, 3, 13)
            ridge_cv = RidgeCV(alphas=alphas, fit_intercept=True, cv=5)
            ridge_cv.fit(X, y_centered, sample_weight=sample_weights_array)

            ridge = Ridge(alpha=ridge_cv.alpha_, fit_intercept=True)
            ridge.fit(X, y_centered, sample_weight=sample_weights_array)

            intercept_adjusted = ridge.intercept_ + y_mean

            offensive_ratings = dict(zip(players, ridge.coef_[:num_players]))
            defensive_ratings = dict(zip(players, ridge.coef_[num_players:]))

            for player in players:
                off_xg_coef = offensive_ratings[player]
                def_xg_coef = defensive_ratings[player]
                update_coef_query = """
                UPDATE players
                SET off_xg_coef = %s, def_xg_coef = %s
                WHERE id = %s
                """
                DB.execute(update_coef_query, (float(off_xg_coef), float(def_xg_coef), player))

            DB.execute("UPDATE leagues SET rag_baseline = %s WHERE id = %s", (float(intercept_adjusted), lid))

    def _train_raw_ras(self):
        """
        Trains raw RAS
        """

        leagues_df = DB.select("SELECT id FROM leagues WHERE is_active = 1 AND to_predict = 1")

        for lid in tqdm(leagues_df['id'].tolist(), desc="League RAS Coeff", unit="league"):
            matches_query = """
            SELECT 
                mg.id, 
                mg.date,
                md.teamA_players, 
                md.teamB_players, 
                md.teamA_sh,
                md.teamB_sh,
                md.minutes_played
            FROM match_general mg
            JOIN match_detailed md
                ON mg.id = md.match_id
            WHERE league_id = %s
            AND DATE(mg.date) < %s
            """
            matches_df = DB.select(matches_query, (lid, self.current_date))

            if matches_df.empty:
                continue 

            matches_df['date'] = pd.to_datetime(matches_df['date'])
            matches_df['days_ago'] = (self.current_date - matches_df['date']).dt.days

            matches_df['teamA_players'] = matches_df['teamA_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
            matches_df['teamB_players'] = matches_df['teamB_players'].apply(lambda v: v if isinstance(v, list) else ast.literal_eval(v))
            matches_df['time_weight'] = np.exp(-np.log(2) * matches_df['days_ago'] / 180)
            total_weight = matches_df['time_weight'].sum()
            matches_df['time_weight'] = matches_df['time_weight'] / total_weight * len(matches_df)

            players_set = set()
            for idx, row in matches_df.iterrows():
                teamA = row['teamA_players'] if isinstance(row['teamA_players'], list) else [row['teamA_players']]
                teamB = row['teamB_players'] if isinstance(row['teamB_players'], list) else [row['teamB_players']]
                players_set.update(teamA)
                players_set.update(teamB)

            players = sorted(list(players_set))
            num_players = len(players)
            players_to_index = {player: idx for idx, player in enumerate(players)}

            rows = []
            cols = []
            data_vals = []
            y = []
            sample_weights = []
            row_num = 0

            for idx, row in matches_df.iterrows():
                minutes = int(row['minutes_played'])
                if minutes == 0:
                    continue
                
                time_weight = float(row['time_weight'])
                teamA_players = row['teamA_players'] if isinstance(row['teamA_players'], list) else [row['teamA_players']]
                teamB_players = row['teamB_players'] if isinstance(row['teamB_players'], list) else [row['teamB_players']]
                teamA_sh = float(row['teamA_sh'])
                teamB_sh = float(row['teamB_sh'])

                # Team A's offensive possessions (positive for offense, negative for defense)
                for p in teamA_players:
                    rows.append(row_num)
                    cols.append(players_to_index[p])
                    data_vals.append(1)
                for p in teamB_players:
                    rows.append(row_num)
                    cols.append(num_players + players_to_index[p])
                    data_vals.append(-1)
                y.append(teamA_sh / minutes)
                sample_weights.append(np.sqrt(minutes * time_weight))
                row_num += 1

                # Team B's offensive possessions
                for p in teamB_players:
                    rows.append(row_num)
                    cols.append(players_to_index[p])
                    data_vals.append(1)
                for p in teamA_players:
                    rows.append(row_num)
                    cols.append(num_players + players_to_index[p])
                    data_vals.append(-1)
                y.append(teamB_sh / minutes)
                sample_weights.append(np.sqrt(minutes * time_weight))
                row_num += 1

            X = sparse.csr_matrix((data_vals, (rows, cols)), shape=(row_num, 2 * num_players))
            y_array = np.array(y)
            sample_weights_array = np.array(sample_weights)

            y_mean = np.average(y_array, weights=sample_weights_array)
            y_centered = y_array - y_mean


            alphas = np.logspace(-3, 3, 13)
            ridge_cv = RidgeCV(alphas=alphas, fit_intercept=True, cv=5)
            ridge_cv.fit(X, y_centered, sample_weight=sample_weights_array)

            ridge = Ridge(alpha=ridge_cv.alpha_, fit_intercept=True)
            ridge.fit(X, y_centered, sample_weight=sample_weights_array)

            intercept_adjusted = ridge.intercept_ + y_mean

            offensive_ratings = dict(zip(players, ridge.coef_[:num_players]))
            defensive_ratings = dict(zip(players, ridge.coef_[num_players:]))

            for player in players:
                off_sh_coef = offensive_ratings[player]
                def_sh_coef = defensive_ratings[player]
                update_coef_query = """
                UPDATE players
                SET off_sh_coef = %s, def_sh_coef = %s
                WHERE id = %s
                """
                DB.execute(update_coef_query, (float(off_sh_coef), float(def_sh_coef), player))

            DB.execute("UPDATE leagues SET ras_baseline = %s WHERE id = %s", (float(intercept_adjusted), lid))
        
    def _update_players_totals(self):
        """
        Sums all data from all players
        """
        update_query  = """
            WITH player_stats AS (
                SELECT 
                    mpb.player_id,
                    COALESCE(SUM(mpb.minutes_played), 0) AS minutes_played,
                    COALESCE(SUM(mpb.fouls_committed), 0) AS fouls_committed,
                    COALESCE(SUM(mpb.fouls_drawn), 0) AS fouls_drawn,
                    COALESCE(SUM(mpb.yellow_cards), 0) AS yellow_cards,
                    COALESCE(SUM(mpb.red_cards), 0) AS red_cards,
                    JSON_OBJECT(
                        'trailing', SUM(CASE WHEN mpb.in_status = 'trailing' THEN 1 ELSE 0 END),
                        'level', SUM(CASE WHEN mpb.in_status = 'level' THEN 1 ELSE 0 END),
                        'leading', SUM(CASE WHEN mpb.in_status = 'leading' THEN 1 ELSE 0 END)
                    ) AS in_status,
                    JSON_OBJECT(
                        'trailing', SUM(CASE WHEN mpb.out_status = 'trailing' THEN 1 ELSE 0 END),
                        'level', SUM(CASE WHEN mpb.out_status = 'level' THEN 1 ELSE 0 END),
                        'leading', SUM(CASE WHEN mpb.out_status = 'leading' THEN 1 ELSE 0 END)
                    ) AS out_status
                FROM match_player_breakdown mpb
                GROUP BY mpb.player_id
            ),
            sub_in_agg AS (
                SELECT 
                    mpb2.player_id,
                    CASE 
                        WHEN COUNT(DISTINCT mpb2.sub_in) = 0 THEN '[]'
                        ELSE CONCAT('[', GROUP_CONCAT(DISTINCT CONCAT('"', REPLACE(mpb2.sub_in, '"', '\\"'), '"')), ']')
                    END AS sub_in_json
                FROM match_player_breakdown mpb2
                WHERE mpb2.sub_in IS NOT NULL AND mpb2.sub_in != ''
                GROUP BY mpb2.player_id
            ),
            sub_out_agg AS (
                SELECT 
                    mpb3.player_id,
                    CASE 
                        WHEN COUNT(DISTINCT mpb3.sub_out) = 0 THEN '[]'
                        ELSE CONCAT('[', GROUP_CONCAT(DISTINCT CONCAT('"', REPLACE(mpb3.sub_out, '"', '\\"'), '"')), ']')
                    END AS sub_out_json
                FROM match_player_breakdown mpb3
                WHERE mpb3.sub_out IS NOT NULL AND mpb3.sub_out != ''
                GROUP BY mpb3.player_id
            )
            UPDATE players p
            INNER JOIN player_stats ps ON p.id = ps.player_id
            LEFT JOIN sub_in_agg sia ON p.id = sia.player_id
            LEFT JOIN sub_out_agg soa ON p.id = soa.player_id
            SET 
                p.minutes_played = ps.minutes_played,
                p.fouls_committed = ps.fouls_committed,
                p.fouls_drawn = ps.fouls_drawn,
                p.yellow_cards = ps.yellow_cards,
                p.red_cards = ps.red_cards,
                p.in_status = ps.in_status,
                p.out_status = ps.out_status,
                p.sub_in = COALESCE(sia.sub_in_json, '[]'),
                p.sub_out = COALESCE(soa.sub_out_json, '[]')
        """

        DB.execute(update_query)

    def _update_reg_totals(self):
        """
        Updates regularization data in leagues
        """
        update_sql = """
        WITH match_minutes AS (
            SELECT
                md.match_id,
                SUM(md.minutes_played) AS match_minutes
            FROM match_detailed md
            GROUP BY md.match_id
        ),
        reg AS (
            SELECT 
                mpb.match_id,
                mg.league_id,
                COALESCE(SUM(fouls_committed),0) AS total_fouls,
                COALESCE(SUM(yellow_cards),0) AS yellow_cards,
                COALESCE(SUM(red_cards),0) AS red_cards,
                mm.match_minutes AS total_minutes
            FROM match_player_breakdown mpb
            LEFT JOIN match_general mg ON mpb.match_id = mg.id
            JOIN match_minutes mm ON mpb.match_id = mm.match_id
            GROUP BY match_id
        ), league_totals AS (
            SELECT
                league_id,
                SUM(total_minutes) AS total_minutes,
                SUM(total_fouls) AS total_fouls,
                SUM(yellow_cards) AS yellow_cards,
                SUM(red_cards) AS red_cards
            FROM reg
            GROUP BY league_id
        )
        UPDATE leagues l
        JOIN league_totals lt ON l.id = lt.league_id
        SET
            l.foul_rate = ROUND(lt.total_fouls/lt.total_minutes, 4),
            l.yc_rate = ROUND(lt.yellow_cards/lt.total_minutes, 4),
            l.rc_rate = ROUND(lt.red_cards/lt.total_minutes, 4)
        """
        DB.execute(update_sql)

    def _train_fatigue_rhythm_model(self):
        """
        Train a fatigue and rhythm spline-model 
        """

        fr_df = DB.select("SELECT * FROM player_fatigue_rhythm")

        # Rhythm (Offense)
        rhythm_df = fr_df[['rhythm', 'r_adjustment']].copy()

        x_rhythm = dmatrix(
            "bs(rhythm, df=5, degree=3, include_intercept=False, lower_bound=0.0, upper_bound=1.0)",
            data=rhythm_df,
            return_type="dataframe"
        )
        rhythm_design_info = x_rhythm.design_info

        y_rhythm = rhythm_df["r_adjustment"]

        rhythm_model = Ridge(alpha=1e-5)
        rhythm_model.fit(x_rhythm, y_rhythm)

        # Fatigue (Defense)
        fatigue_df = fr_df[["fatigue", "f_adjustment"]].copy()

        x_fatigue = dmatrix(
            "bs(fatigue, df=5, degree=3, include_intercept=False, lower_bound=0.0, upper_bound=1.0)",
            data=fatigue_df,
            return_type="dataframe"
        )

        fatigue_design_info = x_fatigue.design_info
        y_fatigue = fatigue_df["f_adjustment"]

        fatigue_model = Ridge(alpha=1e-5)
        fatigue_model.fit(x_fatigue, y_fatigue)

        # Save models
        with open("Database/fatigue_model.pkl", "wb") as fh:
            pickle.dump(fatigue_model, fh)

        with open("Database/rhythm_model.pkl", "wb") as fh:
            pickle.dump(rhythm_model, fh)

        print("Fatigue (def) and Rhythm (off) spline models trained and saved.")

    def _train_contextual_ras_model(self): 
        """
        Train a contextual shots (sh) XGBOOST model using regularized adjusted shots (RAS) as baseline.
        
        This model incorporates contextual factors like elevation differences, travel distance,
        match state, and player quality differences to predict team shots performance. The model
        uses Poisson regression with RAS as base margin and applies sample weighting based
        on minutes played.
        """
        data_query = """ 
        SELECT 
            mg.id,
            mg.home_elevation_dif,
            mg.away_elevation_dif,
            mg.away_travel,
            mg.date,
            SUM(md.teamA_raw_ras) AS teamA_raw_ras,
            SUM(md.teamB_raw_ras) AS teamB_raw_ras,
            SUM(md.minutes_played) AS minutes_played,
            md.time_segment,
            md.match_state,
            md.player_dif,
            SUM(md.teamA_sh) AS teamA_sh,
            SUM(md.teamB_sh) AS teamB_sh
        FROM match_general mg
        JOIN match_detailed md
            ON mg.id = md.match_id
        WHERE md.minutes_strength >= 0.7
        AND md.minutes_played >= 10
        AND DATE(mg.date) < %s
        GROUP BY md.match_id, md.match_state, md.player_dif, md.time_segment 
        """
        context_df = DB.select(data_query, (self.current_date,))
        context_df = context_df.replace([np.inf, -np.inf], np.nan).dropna()
        context_df['home_elevation_dif']  = pd.to_numeric(context_df['home_elevation_dif'],  errors='raise').astype(int)
        context_df['away_elevation_dif']  = pd.to_numeric(context_df['away_elevation_dif'],  errors='raise').astype(int)
        context_df['away_travel']  = pd.to_numeric(context_df['away_travel'],  errors='raise').astype(int)
        context_df['date'] = pd.to_datetime(context_df['date'])
        context_df['teamA_raw_ras']  = pd.to_numeric(context_df['teamA_raw_ras'],  errors='raise').astype(float)
        context_df['teamB_raw_ras']  = pd.to_numeric(context_df['teamB_raw_ras'],  errors='raise').astype(float)
        context_df['minutes_played']  = pd.to_numeric(context_df['minutes_played'],  errors='raise').astype(int)
        context_df['time_segment'] = pd.to_numeric(context_df['time_segment'], errors='raise').astype(int)
        context_df['match_state'] = pd.to_numeric(context_df['match_state'], errors='raise').astype(float)
        context_df['player_dif']  = pd.to_numeric(context_df['player_dif'],  errors='raise').astype(float)
        context_df['teamA_sh']  = pd.to_numeric(context_df['teamA_sh'],  errors='raise').astype(float)
        context_df['teamB_sh']  = pd.to_numeric(context_df['teamB_sh'],  errors='raise').astype(float)

        home_df = pd.DataFrame({
            'sh'                 : context_df['teamA_sh'],
            'raw_ras'            : context_df['teamA_raw_ras'],
            'minutes_played'     : context_df['minutes_played'],
            'time_segment'       : context_df['time_segment'],
            'is_home'            : 1,
            'elevation_dif'      : context_df['home_elevation_dif'],
            'travel'             : -context_df['away_travel'],
            'match_state'        : context_df['match_state'],
            'player_dif'         : context_df['player_dif']
        })

        away_df = pd.DataFrame({
            'sh'                 : context_df['teamB_sh'],
            'raw_ras'            : context_df['teamB_raw_ras'],
            'minutes_played'     : context_df['minutes_played'],
            'time_segment'       : context_df['time_segment'],
            'is_home'            : 0,
            'elevation_dif'      : context_df['away_elevation_dif'],
            'travel'             : context_df['away_travel'],
            'match_state'        : flip(context_df['match_state']),
            'player_dif'         : flip(context_df['player_dif'])
        })
        
        concat_df = pd.concat([home_df, away_df], ignore_index=True)
        clean_df = concat_df.copy()

        clean_df['sh90'] = (clean_df['sh'] / clean_df['minutes_played']) * 90
        clean_df['ras90'] = (clean_df['raw_ras'] / clean_df['minutes_played']) * 90

        cat_cols  = ['match_state', 'player_dif', 'time_segment']
        bool_cols = ['is_home']
        num_cols  = ['elevation_dif', 'travel']
      
        missing_cols  = [c for c in ['sh90', 'ras90'] if c not in clean_df.columns]
        if missing_cols:
            raise ValueError(f'Missing expected columns: {missing_cols}')
        
        sample_weights = np.sqrt(clean_df['minutes_played'] / clean_df['minutes_played'].max())

        for c in cat_cols:
            clean_df[c] = clean_df[c].astype(str).str.lower()

        clean_df[bool_cols] = clean_df[bool_cols].astype(int)

        X_cat = pd.get_dummies(clean_df[cat_cols], prefix=cat_cols)
        X = pd.concat([clean_df[num_cols], clean_df[bool_cols], X_cat], axis=1)

        y = clean_df['sh90']
        base_margin = np.log(clean_df['ras90'].clip(lower=0.01))

        dtrain = xgb.DMatrix(X, label=y, base_margin=base_margin, weight=sample_weights)

        params = dict(objective='count:poisson',
                        tree_method='hist',
                        max_depth=15,
                        eta=0.05,
                        subsample=1.0,
                        colsample_bytree=1.0,
                        min_child_weight=5,
                        gamma=1,
                        reg_alpha=0.5,
                        reg_lambda=1.0,
                        max_delta_step=1)
        
        cv_results = xgb.cv(
            params,
            dtrain,
            num_boost_round=1000,
            nfold=5,
            early_stopping_rounds=50,
            metrics='poisson-nloglik',
            verbose_eval=False
        )
        
        optimal_rounds = len(cv_results)
        booster = xgb.train(params, dtrain, num_boost_round=optimal_rounds)

        booster.save_model('Database/cras_booster.json')

    def _train_contextual_rag_model(self):
        """
        Train a contextual expected goals (xG) XGBOOST model using regularized adjusted xG (RAG) as baseline.
        
        This model incorporates contextual factors like elevation differences, travel distance,
        match state, and player quality differences to predict team xG performance. The model
        uses Poisson regression with RAG as base margin and applies sample weighting based
        on minutes played.
        """
        data_query = """ 
        SELECT 
            mg.id,
            mg.home_elevation_dif,
            mg.away_elevation_dif,
            mg.away_travel,
            mg.date,
            SUM(md.teamA_fr_rag) AS teamA_fr_rag,
            SUM(md.teamB_fr_rag) AS teamB_fr_rag,
            SUM(md.minutes_played) AS minutes_played,
            md.time_segment,
            md.match_state,
            md.player_dif,
            SUM(md.teamA_xg) AS teamA_xg,
            SUM(md.teamB_xg) AS teamB_xg
        FROM match_general mg
        JOIN match_detailed md
            ON mg.id = md.match_id
        WHERE md.minutes_strength >= 0.7
        AND md.minutes_played >= 5
        AND DATE(mg.date) < %s
        AND teamA_fr_rag IS NOT NULL
        AND teamB_fr_rag IS NOT NULL
        GROUP BY md.match_id, md.match_state, md.player_dif, md.time_segment
        """
        context_df = DB.select(data_query, (self.current_date,))
        context_df = context_df.replace([np.inf, -np.inf], np.nan).dropna()
        context_df['home_elevation_dif']  = pd.to_numeric(context_df['home_elevation_dif'],  errors='raise').astype(int)
        context_df['away_elevation_dif']  = pd.to_numeric(context_df['away_elevation_dif'],  errors='raise').astype(int)
        context_df['away_travel']  = pd.to_numeric(context_df['away_travel'],  errors='raise').astype(int)
        context_df['date'] = pd.to_datetime(context_df['date'])
        context_df['teamA_fr_rag']  = pd.to_numeric(context_df['teamA_fr_rag'],  errors='raise').astype(float)
        context_df['teamB_fr_rag']  = pd.to_numeric(context_df['teamB_fr_rag'],  errors='raise').astype(float)
        context_df['minutes_played']  = pd.to_numeric(context_df['minutes_played'],  errors='raise').astype(int)
        context_df['time_segment'] = pd.to_numeric(context_df['time_segment'], errors='raise').astype(int)
        context_df['match_state'] = pd.to_numeric(context_df['match_state'], errors='raise').astype(float)
        context_df['player_dif']  = pd.to_numeric(context_df['player_dif'],  errors='raise').astype(float)
        context_df['teamA_xg']  = pd.to_numeric(context_df['teamA_xg'],  errors='raise').astype(float)
        context_df['teamB_xg']  = pd.to_numeric(context_df['teamB_xg'],  errors='raise').astype(float)

        home_df = pd.DataFrame({
            'xg'                 : context_df['teamA_xg'],
            'fr_rag'            : context_df['teamA_fr_rag'],
            'minutes_played'     : context_df['minutes_played'],
            'time_segment'       : context_df['time_segment'],
            'is_home'            : 1,
            'elevation_dif'      : context_df['home_elevation_dif'],
            'travel'             : -context_df['away_travel'],
            'match_state'        : context_df['match_state'],
            'player_dif'         : context_df['player_dif']
        })

        away_df = pd.DataFrame({
            'xg'                 : context_df['teamB_xg'],
            'fr_rag'            : context_df['teamB_fr_rag'],
            'minutes_played'     : context_df['minutes_played'],
            'time_segment'       : context_df['time_segment'],
            'is_home'            : 0,
            'elevation_dif'      : context_df['away_elevation_dif'],
            'travel'             : context_df['away_travel'],
            'match_state'        : flip(context_df['match_state']),
            'player_dif'         : flip(context_df['player_dif'])
        })
        
        concat_df = pd.concat([home_df, away_df], ignore_index=True)
        clean_df = concat_df.copy()

        clean_df['xg90'] = (clean_df['xg'] / clean_df['minutes_played']) * 90
        clean_df['rag90'] = (clean_df['fr_rag'] / clean_df['minutes_played']) * 90

        cat_cols  = ['match_state', 'player_dif', 'time_segment']
        bool_cols = ['is_home']
        num_cols  = ['elevation_dif', 'travel']
      
        missing_cols  = [c for c in ['xg90', 'rag90'] if c not in clean_df.columns]
        if missing_cols:
            raise ValueError(f'Missing expected columns: {missing_cols}')
        
        sample_weights = np.sqrt(clean_df['minutes_played'] / clean_df['minutes_played'].max())

        for c in cat_cols:
            clean_df[c] = clean_df[c].astype(str).str.lower()

        clean_df[bool_cols] = clean_df[bool_cols].astype(int)

        X_cat = pd.get_dummies(clean_df[cat_cols], prefix=cat_cols)
        X = pd.concat([clean_df[num_cols], clean_df[bool_cols], X_cat], axis=1)

        y = clean_df['xg90']
        base_margin = np.log(clean_df['rag90'].clip(lower=0.01))

        dtrain = xgb.DMatrix(X, label=y, base_margin=base_margin, weight=sample_weights)

        params = dict(objective='count:poisson',
                        tree_method='hist',
                        max_depth=15,
                        eta=0.05,
                        subsample=1.0,
                        colsample_bytree=1.0,
                        min_child_weight=5,
                        gamma=1,
                        reg_alpha=0.5,
                        reg_lambda=1.0,
                        max_delta_step=1)
        
        cv_results = xgb.cv(
            params,
            dtrain,
            num_boost_round=1000,
            nfold=5,
            early_stopping_rounds=50,
            metrics='poisson-nloglik',
            verbose_eval=False
        )
        
        optimal_rounds = len(cv_results)
        booster = xgb.train(params, dtrain, num_boost_round=optimal_rounds)

        booster.save_model('Database/crag_booster.json')

# ------------------------------ Simulation & Odds ------------------------------
class MonteCarloSim:
    """
    Match simulation
    """
    def __init__(self, match_id, home_initial_goals=0, away_initial_goals=0, home_initial_xg=0.0, away_initial_xg=0.0, match_initial_time=0, home_subs_avail=5, away_subs_avail=5, testing=False):
        self.match_id = match_id
        self.testing = testing

        print(f"Simulating {get_match_title(self.match_id)}")
        
        match_df = DB.select("SELECT * FROM schedule WHERE id = %s", (self.match_id,))

        self.home_team_id = int(match_df.iloc[0]['home_team_id'])
        self.away_team_id = int(match_df.iloc[0]['away_team_id'])
        self.match_date = pd.to_datetime(match_df.iloc[0]['date'])
        home_data_raw = match_df.iloc[0]['home_players_data']
        away_data_raw = match_df.iloc[0]['away_players_data']
        if home_data_raw is None or away_data_raw is None:
            raise ValueError("Players data is None")
        self.home_players_init_data = json.loads(home_data_raw)
        self.away_players_init_data = json.loads(away_data_raw)
        self.league_id = int(match_df.iloc[0]['league_id'])
        self.home_elevation_dif = int(match_df.iloc[0]['home_elevation_dif'])
        self.away_elevation_dif = int(match_df.iloc[0]['away_elevation_dif'])
        self.away_travel = int(match_df.iloc[0]['away_travel'])

        self.home_initial_goals = home_initial_goals
        self.away_initial_goals = away_initial_goals
        self.home_initial_xg = home_initial_xg
        self.away_initial_xg = away_initial_xg
        self.match_initial_time = match_initial_time
        self.home_subs_avail = home_subs_avail
        self.away_subs_avail = away_subs_avail

        baseline_df = DB.select("SELECT rag_baseline, ras_baseline FROM leagues WHERE id = %s", (self.league_id,))
        self.rag_baseline_coef = float(baseline_df.iloc[0]['rag_baseline']) if not baseline_df.empty and baseline_df.iloc[0]['rag_baseline'] is not None else 0.0
        self.ras_baseline_coef = float(baseline_df.iloc[0]['ras_baseline']) if not baseline_df.empty and baseline_df.iloc[0]['ras_baseline'] is not None else 0.0    

        self.fatigue_model, self.rhythm_model = load_fr_models()

        self.crag_booster, self.cras_booster, self.boosters_columns = self._load_xgboost_models()
        self.cra_models = {
            'crag': {
                'booster': self.crag_booster,
                'baseline': 'fr_rag'
            },
            'cras': {
                'booster': self.cras_booster,
                'baseline': 'raw_ras'
            }
        }
        precomputed_multipliers = self._precompute_cra_multipliers()
        self.crag_home_multipliers = precomputed_multipliers['crag']['home']
        self.crag_away_multipliers = precomputed_multipliers['crag']['away']
        self.cras_home_multipliers = precomputed_multipliers['cras']['home']
        self.cras_away_multipliers = precomputed_multipliers['cras']['away']

        reg_sql = """
            SELECT
                foul_rate / 2 AS foul_rate,
                yc_rate / foul_rate AS yc_foul,
                rc_rate / foul_rate AS rc_foul
            FROM leagues
            WHERE id = %s
        """
        lrs_df = DB.select(reg_sql, (self.league_id,))
        self.league_regulation_data = lrs_df.iloc[0].to_dict()

        self.home_starters, self.home_subs = self._divide_players("home")
        self.away_starters, self.away_subs = self._divide_players("away")

        self.home_players_data = self._get_players_data("home")
        self.away_players_data = self._get_players_data("away")

        self.home_sub_minutes, self.away_sub_minutes = self._get_sub_minutes()
        self.all_sub_minutes = list(set(list(self.home_sub_minutes.keys()) + list(self.away_sub_minutes.keys())))

        if self.match_initial_time >= 75:
            range_value = 2000
        elif self.match_initial_time >= 60:
            range_value = 4000
        elif self.match_initial_time >= 45:
            range_value = 8000
        elif self.match_initial_time >= 5:
            range_value = 10000
        else:
            range_value = 15000

        if self.testing:
            self._run_simulations(n_sims=10000, n_workers=1, flush_every=100000)
        else:
            self._run_simulations(n_sims=range_value, n_workers=1, flush_every=1000)

    def _load_xgboost_models(self):
        columns = [
            "elevation_dif", 
            "travel", 
            "is_home", 
            "match_state_-0.5", "match_state_-1.5", "match_state_0.0", "match_state_0.5", "match_state_1.5", 
            "player_dif_-0.5", "player_dif_-1.5", "player_dif_0.0", "player_dif_0.5", "player_dif_1.5",
            "time_segment_1", "time_segment_2", "time_segment_3", "time_segment_4", "time_segment_5", "time_segment_6"
        ]
        crag_booster_path  = f'Database/crag_booster.json'
        cras_booster_path  = f'Database/cras_booster.json'

        crag_booster = xgb.Booster()
        cras_booster = xgb.Booster()
        crag_booster.load_model(crag_booster_path)
        cras_booster.load_model(cras_booster_path)

        return crag_booster, cras_booster, columns

    def _simulate_single(self, i: int) -> list:
        """
        Simulates a single game.
        """
        sim_home_players_data = {k: v.copy() for k, v in self.home_players_data.items()}
        sim_away_players_data = {k: v.copy() for k, v in self.away_players_data.items()}

        home_goals = self.home_initial_goals
        away_goals = self.away_initial_goals
        home_xg = self.home_initial_xg
        away_xg = self.away_initial_xg
        home_active_players  = self.home_starters.copy()
        away_active_players  = self.away_starters.copy()
        home_inactive_players = self.home_subs.copy()
        away_inactive_players = self.away_subs.copy()

        score_rows = []

        home_status, away_status = self._get_status(home_goals, away_goals)
        time_segment = self._get_time_segment(self.match_initial_time)

        home_fr_rag = self._get_teams_fr_rag(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data)
        away_fr_rag = self._get_teams_fr_rag(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data)

        home_raw_ras = self._get_teams_raw_ras(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data)
        away_raw_ras = self._get_teams_raw_ras(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data)

        home_g_mult = self.crag_home_multipliers[(home_status, self._get_player_dif(len(home_active_players), len(away_active_players)), time_segment)]
        away_g_mult = self.crag_away_multipliers[(away_status, self._get_player_dif(len(away_active_players), len(home_active_players)), time_segment)]
        home_proj_goals = max(1e-6, home_fr_rag) * home_g_mult
        away_proj_goals = max(1e-6, away_fr_rag) * away_g_mult

        home_s_mult = self.cras_home_multipliers[(home_status, self._get_player_dif(len(home_active_players), len(away_active_players)), time_segment)]
        away_s_mult = self.cras_away_multipliers[(away_status, self._get_player_dif(len(away_active_players), len(home_active_players)), time_segment)]
        home_proj_shots = max(1e-6, home_raw_ras) * home_s_mult
        away_proj_shots = max(1e-6, away_raw_ras) * away_s_mult
        
        home_foul_rate = self._get_team_foul_prob(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data, home_status, time_segment, is_home=True)
        away_foul_rate = self._get_team_foul_prob(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data, away_status, time_segment, is_home=False)

        score_rows.append((i, self.match_initial_time, home_goals, away_goals, home_xg, away_xg))
        fr_rag_change = False 

        for minute in range(self.match_initial_time, 90):
            if minute in [16, 31, 46, 61, 76]:
                time_segment = self._get_time_segment(minute)
                fr_rag_change = True

            if minute in self.all_sub_minutes:
                fr_rag_change = True
                home_in_players = []
                away_in_players = []

                if minute in list(self.home_sub_minutes.keys()):
                    home_active_players, home_inactive_players, home_in_players = self._swap_players(home_active_players, home_inactive_players, sim_home_players_data, self.home_sub_minutes[minute], home_status)
                if minute in list(self.away_sub_minutes.keys()):
                    away_active_players, away_inactive_players, away_in_players = self._swap_players(away_active_players, away_inactive_players, sim_away_players_data, self.away_sub_minutes[minute], away_status)

            if fr_rag_change:
                fr_rag_change = False

                home_fr_rag = self._get_teams_fr_rag(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data)
                away_fr_rag = self._get_teams_fr_rag(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data)

                home_raw_ras = self._get_teams_raw_ras(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data)
                away_raw_ras = self._get_teams_raw_ras(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data)

                home_g_mult = self.crag_home_multipliers[(home_status, self._get_player_dif(len(home_active_players), len(away_active_players)), time_segment)]
                away_g_mult = self.crag_away_multipliers[(away_status, self._get_player_dif(len(away_active_players), len(home_active_players)), time_segment)]
                home_proj_goals = max(1e-6, home_fr_rag) * home_g_mult
                away_proj_goals = max(1e-6, away_fr_rag) * away_g_mult

                home_s_mult = self.cras_home_multipliers[(home_status, self._get_player_dif(len(home_active_players), len(away_active_players)), time_segment)]
                away_s_mult = self.cras_away_multipliers[(away_status, self._get_player_dif(len(away_active_players), len(home_active_players)), time_segment)]
                home_proj_shots = max(1e-6, home_raw_ras) * home_s_mult
                away_proj_shots = max(1e-6, away_raw_ras) * away_s_mult

                home_foul_rate = self._get_team_foul_prob(home_active_players, away_active_players, sim_home_players_data, sim_away_players_data, home_status, time_segment, is_home=True)
                away_foul_rate = self._get_team_foul_prob(away_active_players, home_active_players, sim_away_players_data, sim_home_players_data, away_status, time_segment, is_home=False)

            home_n_shots_pm, home_xg_pm = self._simulate_minute_xg(home_proj_goals, home_proj_goals/home_proj_shots)
            away_n_shots_pm, away_xg_pm = self._simulate_minute_xg(away_proj_goals, away_proj_goals/away_proj_shots)

            home_xg += home_xg_pm
            away_xg += away_xg_pm

            home_goals_scored = 0
            if home_n_shots_pm > 0:
                p_shot = home_xg_pm / home_n_shots_pm
                p_shot = min(p_shot, 1.0) 
                home_goals_scored = np.sum(np.random.random(size=home_n_shots_pm) < p_shot)

            away_goals_scored = 0
            if away_n_shots_pm > 0:
                p_shot = away_xg_pm / away_n_shots_pm
                p_shot = min(p_shot, 1.0)
                away_goals_scored = np.sum(np.random.random(size=away_n_shots_pm) < p_shot)

            if home_goals_scored:
                home_goals += home_goals_scored
                home_status, away_status = self._get_status(home_goals, away_goals)
                fr_rag_change = True

            if away_goals_scored:
                away_goals += away_goals_scored
                home_status, away_status = self._get_status(home_goals, away_goals)
                fr_rag_change = True

            if self.testing:
                if minute == 89:
                    score_rows.append((i, minute, home_goals, away_goals, home_xg, away_xg))
            else:
                if home_xg_pm or away_xg_pm:
                    score_rows.append((i, minute, home_goals, away_goals, home_xg, away_xg))

            home_fouls = np.random.poisson(home_foul_rate)
            for _ in range(home_fouls):
                fouler = self._choose_fouler(home_active_players, sim_home_players_data)
                card_type  = self._determine_card(fouler, self.home_players_data)

                if card_type == 'YC':
                    if sim_home_players_data[fouler]['yellow_card'] == True:
                        sim_home_players_data[fouler]['red_card'] = True
                        home_active_players.remove(fouler)
                        fr_rag_change = True
                    else:
                        sim_home_players_data[fouler]['yellow_card'] = True

                elif card_type == 'RC':
                    sim_home_players_data[fouler]['red_card'] = True
                    home_active_players.remove(fouler)
                    fr_rag_change = True
                    

            away_fouls = np.random.poisson(away_foul_rate)
            for _ in range(away_fouls):
                fouler = self._choose_fouler(away_active_players, sim_away_players_data)
                card_type  = self._determine_card(fouler, self.away_players_data)

                if card_type == 'YC':
                    if sim_away_players_data[fouler]['yellow_card'] == True:
                        sim_away_players_data[fouler]['red_card'] = True
                        away_active_players.remove(fouler)
                        fr_rag_change = True
                    else:
                        sim_away_players_data[fouler]['yellow_card'] = True

                elif card_type == 'RC':
                    sim_away_players_data[fouler]['red_card'] = True
                    away_active_players.remove(fouler)
                    fr_rag_change = True
                    
        return score_rows

    def _run_simulations(self, n_sims: int, n_workers: int, flush_every: int):
        """
        Runs Monte Carlo simulations in parallel (if possible) and saves results to a database in batches to manage memory usage
        """
        if n_workers is None:
            n_workers = os.cpu_count() or 1

        score_buf = []
        first_flush_done = False

        def _flush():
            nonlocal first_flush_done
            if not score_buf:
                return
            self._insert_buf(rows=score_buf, initial_delete=not first_flush_done)
            first_flush_done = True
            score_buf.clear()

        if n_workers > 1:
            with multiprocessing.Pool(processes=n_workers) as pool:
                for idx, score_rows in enumerate(tqdm(pool.imap_unordered(self._simulate_single, range(n_sims)), total=n_sims, desc=f'Simulations ({n_workers} workers)')):
                    score_buf.extend(score_rows)
                    if (idx + 1) % flush_every == 0:
                        _flush()
        else:
            for idx in tqdm(range(n_sims), desc='Simulations (1 worker)'):
                score_rows = self._simulate_single(idx)
                score_buf.extend(score_rows)
                if (idx + 1) % flush_every == 0:
                    _flush()

        _flush()

    def _predict_cra(self, new_match, *, booster, baseline_col, raw=False):
        match_data = new_match.copy()

        cat_cols  = ['match_state', 'player_dif', 'time_segment']
        bool_cols = ['is_home']
        num_cols  = ['elevation_dif', 'travel']
        
        base_margin = np.log(match_data.pop(baseline_col).clip(lower=0.01))

        for col in cat_cols:
            match_data[col] = match_data[col].astype(str).str.lower()
        
        for col in bool_cols:
            match_data[col] = match_data[col].astype(int)

        new_cat = pd.get_dummies(match_data[cat_cols], prefix=cat_cols)

        new_X = pd.concat([match_data[num_cols + bool_cols].reset_index(drop=True), new_cat.reset_index(drop=True)], axis=1)
        new_X = new_X.reindex(columns=self.boosters_columns, fill_value=0)

        dmatrix = xgb.DMatrix(new_X, base_margin=base_margin)
        prediction = booster.predict(dmatrix, output_margin=raw)

        return prediction[0]

    def _precompute_cra_multipliers(self):
        """
        Precomputes the predictions of the XG Boost model on RAxG for efficiency
        """
        def _template(is_home):
            return {
                'is_home'       : int(is_home),
                'elevation_dif' : self.home_elevation_dif if is_home else self.away_elevation_dif,
                'travel'        : -self.away_travel if is_home else self.away_travel,
                'fr_rag'        : 1.0,
                'raw_ras'       : 1.0
            }

        states       = [-1.5, -0.5, 0, 0.5, 1.5]
        player_diffs = [-1.5, -0.5, 0, 0.5, 1.5]
        time_segments = [1, 2, 3, 4, 5, 6]

        results = {}
        for name, cfg in self.cra_models.items():
            home_cache, away_cache = {}, {}

            for st, pdif, ts in itertools.product(states, player_diffs, time_segments):
                for is_home, cache in ((True, home_cache), (False, away_cache)):
                    row = _template(is_home)
                    row.update({'match_state': st, 'player_dif': pdif, 'time_segment': ts})

                    raw_margin = self._predict_cra(
                        pd.DataFrame([row]),
                        booster=cfg['booster'],
                        baseline_col=cfg['baseline']
                    )
                    
                    cache[(st, pdif, ts)] = raw_margin
            results[name] = {
                'home': home_cache,
                'away': away_cache
            }
        return results

    def _divide_players(self, team: str) -> tuple[list[str], list[str]]:
        if team == "home":
            players_data = self.home_players_init_data
        elif team == "away":
            players_data = self.away_players_init_data

        starters = [p['player_id'] for p in players_data if p['on_field']]
        subs = [p['player_id'] for p in players_data if p['bench']]
        return starters, subs

    def _get_players_data(self, team: str) -> dict:
        """
        Returns all the neccesary data for each active player
        """
        if team == "home":
            all_players = self.home_starters + self.home_subs
            initial_player_data = self.home_players_init_data
        elif team == "away":
            all_players = self.away_starters + self.away_subs
            initial_player_data = self.away_players_init_data

        escaped_players = [player.replace("'", "''") for player in all_players]
        players_str = ", ".join([f"'{player}'" for player in escaped_players])

        sql_query = f"""
            SELECT 
                *
            FROM players
            WHERE id IN ({players_str});
        """
        players_df = DB.select(sql_query)

        initial_mapping = {}
        if initial_player_data is not None:
            initial_mapping = {player['player_id']: player for player in initial_player_data}

        players_dict = {}
        for player_id in all_players:
            if player_id in players_df['id'].values:
                player_row = players_df[players_df['id'] == player_id]
                player_sql_data = player_row.iloc[0].to_dict()
                player_sql_data['minutes_played'] = player_sql_data.get('minutes_played') if pd.notna(player_sql_data.get('minutes_played')) else 0
                player_sql_data['fouls_committed_rate'] = self._get_rate(player_sql_data.get('fouls_committed'), player_sql_data.get('minutes_played'))
                player_sql_data['fouls_drawn_rate'] = self._get_rate(player_sql_data.get('fouls_drawn'), player_sql_data.get('minutes_played'))
                player_sql_data['yellow_card_rate'] = self._get_rate(player_sql_data.get('yellow_cards'), player_sql_data.get('fouls_committed'))
                player_sql_data['red_card_rate'] = self._get_rate(player_sql_data.get('red_cards'), player_sql_data.get('fouls_committed'))
                player_sql_data['sub_in_count'] = self._sub_count(player_sql_data.get('sub_in'))
                player_sql_data['sub_out_count'] = self._sub_count(player_sql_data.get('sub_out'))
                player_sql_data['in_status_prob'] = self._status_prob(player_sql_data.get('in_status'))
                player_sql_data['out_status_prob'] = self._status_prob(player_sql_data.get('out_status'))
                player_sql_data['out_status_prob'] = self._status_prob(player_sql_data.get('out_status'))
                player_sql_data['fr_xg_off_coef'] = predict_fr_coef(
                    mode="rhythm",
                    coef=player_sql_data['off_xg_coef'] if pd.notna(player_sql_data['off_xg_coef']) else 0,
                    feature=player_sql_data['rhythm'] if pd.notna(player_sql_data['rhythm']) else 0,
                    model=self.rhythm_model
                )
                player_sql_data['fr_xg_def_coef'] = predict_fr_coef(
                    mode="fatigue",
                    coef=player_sql_data['def_xg_coef'] if pd.notna(player_sql_data['def_xg_coef']) else 0,
                    feature=player_sql_data['fatigue'] if pd.notna(player_sql_data['fatigue']) else 0,
                    model=self.fatigue_model
                )

                delete_columns = ['id', 'team_id', 'off_xg_coef', 'def_xg_coef', 'fouls_committed', 'fouls_drawn', 'yellow_cards', 'red_cards', 'sub_in', 'sub_out', 'in_status', 'out_status', 'fatigue', 'rhythm']
                player_sql_data = {k: v for k, v in player_sql_data.items() if k not in delete_columns}
                players_dict[player_id] = player_sql_data
            else:
                players_dict[player_id] = {
                    'minutes_played': 0,
                    'fr_xg_off_coef': 0.0,
                    'fr_xg_def_coef': 0.0,
                    'off_sh_coef': 0.0,
                    'def_sh_coef': 0.0,
                    'fouls_committed_rate': 0.0,
                    'fouls_drawn_rate': 0.0,
                    'yellow_card_rate': 0.0,
                    'red_card_rate': 0.0,
                    'sub_in_count': 0,
                    'sub_out_count': 0,
                    'in_status_prob': {'Leading': 0.33, 'Level': 0.33, 'Trailing': 0.33},
                    'out_status_prob': {'Leading': 0.33, 'Level': 0.33, 'Trailing': 0.33},
                }

            if player_id in initial_mapping:
                extracted = initial_mapping[player_id]
                players_dict[player_id]['bench'] = extracted.get('bench')
                players_dict[player_id]['on_field'] = extracted.get('on_field')
                players_dict[player_id]['yellow_card'] = extracted.get('yellow_card')
                players_dict[player_id]['red_card'] = extracted.get('red_card')
            else:
                continue

        return players_dict

    def _get_rate(self, numerator: int, denominator: int) -> float:
        if denominator and denominator > 0 and numerator:
            if numerator >= denominator:
                return 1.0
            else:
                return numerator / denominator
        else:
            return 0.0
        
    def _sub_count(self, raw_str: str) -> float:
        count = 0
        try:
            sub_in_list = eval(raw_str)
            count = len(sub_in_list)
        except:
            pass

        return count
    
    def _status_prob(self, raw_str: str) -> dict:
        counts = {}
        try:
            counts = ast.literal_eval(raw_str)
        except:
            pass

        counts = {k.title(): v for k, v in counts.items()}
        base = {'Leading': 0, 'Level': 0, 'Trailing': 0}
        base.update(counts)

        smoothed = {k: v + 1 for k, v in base.items()}

        total = sum(smoothed.values())
        return {k: v / total for k, v in smoothed.items()}

    def _get_sub_minutes(self) -> tuple[dict, dict]:
        """
        Returns a dictionary per team for the most common sub windows, and how many subs to do
        """
        teams_query = """ 
            SELECT 
                mpb.match_id,
                mpb.sub_in AS sub_minute,
                p.team_id
            FROM match_player_breakdown mpb
            JOIN players p
                ON mpb.player_id = p.id
            WHERE p.team_id IN (%s, %s)
            AND mpb.sub_in IS NOT NULL
        """

        teams_df = DB.select(teams_query, (self.home_team_id, self.away_team_id))
        teams_df = teams_df.dropna()

        home_avg_subs = round(teams_df[teams_df['team_id'] == self.home_team_id].groupby('match_id').size().mean())
        away_avg_subs = round(teams_df[teams_df['team_id'] == self.away_team_id].groupby('match_id').size().mean())

        effective_home_subs = max(0, min(home_avg_subs - (5 - self.home_subs_avail), self.home_subs_avail))
        effective_away_subs = max(0, min(away_avg_subs - (5 - self.away_subs_avail), self.away_subs_avail))

        home_distribution = self._get_distribution("home", effective_home_subs)
        away_distribution = self._get_distribution("away", effective_away_subs)

        return home_distribution, away_distribution

    def _get_distribution(self, team: str, effective_subs: int) -> dict:
        if team == "home":
            team_id = self.home_team_id
            avail_subs = self.home_subs_avail
        else:
            team_id = self.away_team_id
            avail_subs = self.away_subs_avail

        if effective_subs == 0:
            return {100: 0}
        elif effective_subs == 1:
            n_windows = 1
        elif effective_subs < 5:
            n_windows = 2
        else:
            n_windows = 3

        top_minutes = self._get_future_sub_minutes(self.match_initial_time, n_windows)

        base = avail_subs // n_windows
        remainder = avail_subs % n_windows
        distribution = {}
        for i in range(n_windows):
            minute = top_minutes[i]
            distribution[round(min(90, minute))] = distribution.get(minute, 0) + (base + 1 if i < remainder else base)
        return distribution

    def _get_future_sub_minutes(self, current_minute: int, n_windows: int) -> list:
        minutes_df = DB.select("SELECT mpb.sub_in AS sub_minute FROM match_player_breakdown mpb WHERE mpb.sub_in IS NOT NULL", ())
        minutes_df = minutes_df.dropna()

        minutes = minutes_df["sub_minute"].clip(upper=89)
        counts = minutes.value_counts().sort_index()
        probabilities = counts / counts.sum()

        future = probabilities[probabilities.index >= current_minute]
        future = future / future.sum()

        return np.random.choice(
                future.index,
                size=n_windows,
                replace=False,
                p=future.values
            )

    def _swap_players(self, active_players: list, inactive_players: list, players_data: dict, subs: int, status: float) -> tuple[list, list, list]:
        if status > 0:
            status = "Leading"
            off_ratio, def_ratio = 0.2, 0.8
        elif status < 0:
            status = "Trailing"
            off_ratio, def_ratio = 0.8, 0.2
        else:
            status = "Level"
            off_ratio, def_ratio = 0.5, 0.5

        def _get_tactical_score(p_name):
            p = players_data[p_name]
            return (p['fr_xg_off_coef'] * off_ratio) + (p['fr_xg_def_coef'] * def_ratio)

        # Sub out
        out_scores = {}
        
        total_minutes_out = sum(players_data[p]['minutes_played'] + 1 for p in active_players)
        total_tactical_out = sum(_get_tactical_score(p) + 1 for p in active_players)

        for player in active_players:
            p_data = players_data[player]
            score_history = (p_data['sub_out_count'] + 1) * p_data['out_status_prob'][status] 
            score_hierarchy = 1 / ((p_data['minutes_played'] / 100) + 1)**2
            score_tactical = 1 / (_get_tactical_score(player) + 0.1)

            out_scores[player] = score_history * score_hierarchy * score_tactical

        total_out = sum(out_scores.values())
        out_probs = [s / total_out for s in out_scores.values()]
        out_prob_map = {player: (score / total_out) for player, score in out_scores.items()}
        picked_out_players = np.random.choice(active_players, p=out_probs, replace=False, size=subs)

        # Sub in
        in_scores = {}

        total_minutes_in = sum(players_data[p]['minutes_played'] + 1 for p in inactive_players)
        total_tactical_in = sum(_get_tactical_score(p) + 1 for p in inactive_players)

        for player in inactive_players:
            p_data = players_data[player]
            score_history = (p_data['sub_in_count'] + 1) * p_data['in_status_prob'][status]
            score_hierarchy = (p_data['minutes_played'] / 100) + 1
            score_tactical = _get_tactical_score(player) + 0.1

            in_scores[player] = score_history * score_hierarchy * score_tactical

        total_in = sum(in_scores.values())
        in_probs = [s / total_in for s in in_scores.values()]
        in_prob_map = {player: (score / total_in) for player, score in in_scores.items()}
        picked_in_players = np.random.choice(inactive_players, p=in_probs, replace=False, size=subs)

        active_players = [player for player in active_players if player not in picked_out_players]
        active_players.extend(picked_in_players)
        inactive_players = [player for player in inactive_players if player not in picked_in_players]

        return active_players, inactive_players, picked_in_players

    def _get_teams_fr_rag(self, offensive_players: list, defensive_players: list, offensive_data: dict, defensive_data: dict) -> float:
        team_off_fr_rag = sum(
            offensive_data[p]['fr_xg_off_coef']
            for p in offensive_players
        )

        opp_def_fr_rag = sum(
            defensive_data[p]['fr_xg_def_coef']
            for p in defensive_players
        )

        fr_rag = self.rag_baseline_coef + team_off_fr_rag - opp_def_fr_rag

        return fr_rag
 
    def _get_teams_raw_ras(self, offensive_players: list, defensive_players: list, offensive_data: dict, defensive_data: dict) -> float:
        team_off_raw_ras = sum(
            offensive_data[p]['off_sh_coef']
            for p in offensive_players
        )

        opp_def_raw_ras = sum(
            defensive_data[p]['def_sh_coef']
            for p in defensive_players
        )

        raw_ras = self.ras_baseline_coef + team_off_raw_ras - opp_def_raw_ras

        return raw_ras

    def _get_status(self, home_goals: int, away_goals: int) -> tuple[float, float]:
        diff = home_goals - away_goals
        if diff == 0:
            return 0.0, 0.0
        elif diff == 1:
            return 0.5, -0.5
        elif diff > 1:
            return 1.5, -1.5
        elif diff == -1:
            return -0.5, 0.5
        elif diff < -1:
            return -1.5, 1.5

    def _get_time_segment(self, minute: int) -> int:
        return min((minute // 15) + 1, 6)

    def _get_player_dif(self, team_n_players: int, opp_n_players: int) -> float:
        team_player_dif = team_n_players - opp_n_players
        output = 0.0

        if team_player_dif > 1:
            output = 1.5
        elif team_player_dif == 1:
            output = 0.5
        elif team_player_dif < -1:
            output = -1.5
        elif team_player_dif == -1:
            output = -0.5
        else:
            pass

        return output

    def _simulate_minute_xg(self, lam: float, mean_xg_unit: float) -> tuple[int, float]:
        n = np.random.poisson(lam / mean_xg_unit)

        if n == 0:
            return 0, 0.0

        xg_chunks = np.random.exponential(
            scale=mean_xg_unit,
            size=n
        )

        return n, xg_chunks.sum()

    def _insert_buf(self, rows: list, *, initial_delete: bool) -> None:
        def to_builtin(x):
            if isinstance(x, (np.generic,)):
                return x.item()
            return x
        
        if initial_delete:
            DB.execute("DELETE FROM simulation WHERE match_id = %s", (self.match_id,))

        batch_size = 200
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            placeholders = ', '.join(['(%s, %s, %s, %s, %s, %s, %s)'] * len(chunk))
            insert_sql = f"""
            INSERT INTO simulation 
                (sim_id, match_id, minute, home_goals, away_goals, home_xg, away_xg)
            VALUES {placeholders}
            """
            params = []
            for row in chunk:
                params.extend([to_builtin(row[0]), to_builtin(self.match_id)] + [to_builtin(x) for x in row[1:7]])

            DB.execute(insert_sql, params)

    def _regulation_factors(self, ha: bool, status: float, time: int) -> float:
        ha_factor   = {True: 0.95, False: 1.05}
        status_factor = {-1.5: 1.1, -0.5: 1.05, 0: 1.0, 0.5: 0.95, 1.5: 0.9}
        time_factor = {1: 0.90, 2: 0.95, 3: 0.98, 4: 1.02, 5: 1.05, 6: 1.10}

        ha_val = ha_factor[ha]
        status_val = status_factor[status]
        time_val = time_factor[time]
        
        return ha_val * status_val * time_val

    def _get_team_foul_prob(self, team_players: list, opp_players: list, team_data: dict, opp_data: dict, status: float, time_segment: int, is_home: bool) -> float:
        league_foul_rate = self.league_regulation_data['foul_rate']

        team_foul_committed_rate = sum(team_data[player]['fouls_committed_rate'] for player in team_players)
        opp_foul_drawn_rate = sum(opp_data[player]['fouls_drawn_rate'] for player in opp_players)
        
        reg_factor = self._regulation_factors(is_home, status, time_segment)

        return ((0.5 * league_foul_rate) + (0.25 * team_foul_committed_rate) + (0.25 * opp_foul_drawn_rate)) * reg_factor
    
    def _choose_fouler(self, active_players: list, players_data: dict) -> str:
        total_foul_rate = sum(players_data[player]['fouls_committed_rate'] + 0.001 for player in active_players)
        foul_prob = {player: (((players_data[player]['fouls_committed_rate'] + 0.001) / total_foul_rate)) for player in active_players}

        weights = list(foul_prob.values())

        return np.random.choice(active_players, p=weights)
    
    def _determine_card(self, player_id: str, players_data: dict) -> str:
        player_data = players_data[player_id]

        player_yellow_card_rate = player_data.get('yellow_card_rate')
        player_red_card_rate = player_data.get('red_card_rate')

        league_yellow_card_rate = self.league_regulation_data.get('yc_foul')
        league_red_card_rate = self.league_regulation_data.get('rc_foul')

        yc_prob = (league_yellow_card_rate * 0.75) + (player_yellow_card_rate * 0.25)
        rc_prob = (league_red_card_rate * 0.75) + (player_red_card_rate * 0.25)
        none_prob = 1 - yc_prob - rc_prob

        probs = [yc_prob, rc_prob, none_prob]

        return np.random.choice(['YC', 'RC', 'NONE'], p=probs)

class OddsPortal:
    def __init__(self, from_date: date, to_date: date, leagues_id: list, update_real_xg: bool = False):
        self.from_date = from_date
        self.to_date = to_date
        self.ids_str = ','.join(map(str, leagues_id))

        if update_real_xg:
            # self._fix_team_names_before_update()
            self._update_odds_real_xg()
        else:
            matches_data = self._get_matches_url()

            for match_data in tqdm(matches_data, desc="Processing matches", unit="match"):
                self._scrape_odds(match_data)

            self._update_odds_real_xg()

    def _get_matches_url(self) -> dict:
        active_leagues_df = DB.select(f"SELECT * FROM leagues WHERE id IN ({self.ids_str})")

        matches_data = []
        pbar = tqdm(active_leagues_df.to_dict('records'), desc="Processing leagues", unit="league")

        for league in pbar:
            league_name = get_league_name_by_id(league['id'])
            pbar.set_postfix({"league": league_name})
            
            teams = DB.select("SELECT id, name FROM teams WHERE league_id = %s", (league['id'],))
            team_records = teams.to_dict('records')
            team_names = {preprocess_for_matching(team['name']): team for team in team_records}

            with SeleniumManager(simple_mode=True) as driver:
                driver.get(league['odds_url'])
                time.sleep(5)

                self._click_out_ads(driver)

                driver.execute_script("window.scrollBy(0, 3000);")
                time.sleep(1)

                page_source = driver.page_source
                
            soup = BeautifulSoup(page_source, "html.parser")

            game_rows = soup.select('[data-testid="game-row"]')
            
            for game_row in game_rows:
                try:
                    date_header = game_row.find_previous(attrs={"data-testid": "date-header"})

                    if not date_header:
                        continue

                    date_element = date_header.select_one('.text-black-main')

                    if not date_element:
                        continue

                    date_str = date_element.get_text(strip=True)
                    date_part = date_str.split(' - ')[0].strip()

                    try:
                        match_date = datetime.strptime(date_part, '%d %b %Y').date()
                    except ValueError:
                        print(f"Could not parse date: {date_part}")
                        continue

                    if not (self.from_date <= match_date <= self.to_date):
                        continue

                    link_element = game_row.select_one('a[href*="/football/"]')

                    if not link_element or 'href' not in link_element.attrs:
                        continue
                    
                    href = link_element['href']
                    
                    if href.startswith('/'):
                        href = f"https://www.oddsportal.com{href}"
                    
                    team_elements = game_row.select('.participant-name')
                    home_team_raw = team_elements[0].get_text(strip=True) if len(team_elements) > 0 else ""
                    away_team_raw = team_elements[1].get_text(strip=True) if len(team_elements) > 1 else ""

                    home_team_match = self._find_best_match(home_team_raw, team_names)
                    away_team_match = self._find_best_match(away_team_raw, team_names)
                    
                    game_data = {
                        'date': match_date,
                        'home_team': home_team_match['name'] if home_team_match else home_team_raw,
                        'away_team': away_team_match['name'] if away_team_match else away_team_raw,
                        'league': league_name,
                        'url': href
                    }

                    matches_data.append(game_data)
                    
                except Exception as e:
                    #print(f"Error processing game row: {e}")
                    continue
        pbar.close()
        return matches_data

    def _find_best_match(self, team_name: str, team_names: dict):
        processed_name = preprocess_for_matching(team_name)
        match = process.extractOne(
            processed_name, 
            team_names.keys(), 
            scorer=fuzz.token_sort_ratio,
            score_cutoff=80 
        )
        return team_names[match[0]] if match else None

    def _scrape_odds(self, match_data: dict) -> None:
        home_odds_list, draw_odds_list, away_odds_list = [], [], []
        over_under_data = {}
        asian_handicap_data = {}
        score_data = {}
        home_goals = 0
        away_goals = 0

        allowed_scores = {
            "0-0", "1-0", "0-1", "1-1", "2-0", "0-2", "2-1", "1-2", 
            "2-2", "3-0", "0-3", "3-1", "1-3", "3-2", "2-3", "3-3"
        }

        with SeleniumManager(use_profile=True) as driver:
            print(match_data['url'])
            driver.get(match_data['url'])
            time.sleep(3)
            self._click_out_ads(driver)

            # GOALS & MONEYLINE
            soup = BeautifulSoup(driver.page_source, "html.parser")
            try:
                home_goals_el = soup.select_one("[data-testid='game-host'] + div")
                home_goals = home_goals_el.get_text(strip=True) if home_goals_el else "0"

                guest_el = soup.find("div", {"data-testid": "game-guest"})
                if guest_el:
                    away_goals_el = guest_el.find_previous_sibling("div")
                    away_goals = away_goals_el.get_text(strip=True) if away_goals_el else "0"

            except Exception as e:
                print(f"Could not extract goals from page: {e}")

            # Moneyline
            rows = soup.select('[data-testid="over-under-expanded-row"]')
            
            for row in rows:
                odds_elements = row.select('[data-testid="odd-container"] .odds-text')

                if len(odds_elements) >= 3:
                    try:
                        home_odds_list.append(float(odds_elements[0].get_text(strip=True)))
                        draw_odds_list.append(float(odds_elements[1].get_text(strip=True)))
                        away_odds_list.append(float(odds_elements[2].get_text(strip=True)))
                    except ValueError:
                        continue

            # OVER/UNDER
            try:
                tab = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='bet-types-nav']//li[contains(., 'Over/Under')]")))
                driver.execute_script("arguments[0].click();", tab)
                time.sleep(1)

                soup = BeautifulSoup(driver.page_source, "html.parser")
                rows = soup.select('[data-testid="over-under-collapsed-row"]')
            
                for row in rows:
                    option_box = row.select_one('[data-testid="over-under-collapsed-option-box"]')
                    if not option_box: continue

                    option_text = option_box.get_text(strip=True)
                        
                    match = re.search(r'\+(\d+(\.\d+)?)', option_text)

                    if match:
                        threshold = float(match.group(1))
                        if threshold in [1.5, 2.5, 3.5]:
                            odd_elements = row.select('[data-testid="odd-container-default"] p')
                            if len(odd_elements) >= 2:                                
                                over_under_data[threshold] = {
                                    'over': float(odd_elements[0].get_text(strip=True)),
                                    'under': float(odd_elements[1].get_text(strip=True))
                                }
            except Exception:
                pass
            
            # ASIAN HANDICAP
            try:
                tab = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='bet-types-nav']//li[contains(., 'Asian Handicap')]")))
                driver.execute_script("arguments[0].click();", tab)
                time.sleep(1)

                soup = BeautifulSoup(driver.page_source, "html.parser")
                rows = soup.select('[data-testid="over-under-collapsed-row"]')
                
                for row in rows:
                    option_box = row.select_one('[data-testid="over-under-collapsed-option-box"]')
                    if not option_box: continue

                    option_text = option_box.get_text(strip=True)
                    match = re.search(r'([+-]?\d+(?:\.\d+)?)', option_text)
                    if match:
                        threshold = float(match.group(1))
                        
                        if threshold in [-0.75, -0.25, 0, 0.25, 0.75]:
                            odd_elements = row.select('[data-testid="odd-container-default"] p')
                        
                        if len(odd_elements) >= 2:                                
                            asian_handicap_data[threshold] = {
                                'home': float(odd_elements[0].get_text(strip=True)),
                                'away': float(odd_elements[1].get_text(strip=True))
                            }       
            except Exception:
                pass

            # CORRECT SCORE
            try:
                try:
                    tab = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='bet-types-nav']//li[contains(., 'Correct Score')]")))
                    driver.execute_script("arguments[0].click();", tab)
                except Exception:
                    more_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='more-button']")))
                    driver.execute_script("arguments[0].click();", more_btn)
                    
                    tab = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//ul[contains(@class, 'hidden-links')]//li[contains(., 'Correct Score')]")))
                    driver.execute_script("arguments[0].click();", tab)

                time.sleep(1)

                soup = BeautifulSoup(driver.page_source, "html.parser")
                rows = soup.select('[data-testid="over-under-collapsed-row"]')

                for row in rows:
                    option_box = row.select_one('[data-testid="over-under-collapsed-option-box"]')
                    if not option_box: continue

                    score_text = option_box.select_one('p').get_text(strip=True).replace(':', '-')

                    if score_text in allowed_scores:
                        odd_element = row.select_one('[data-testid="odd-container-default"] p')
                        if odd_element:
                            score_data[score_text] = float(odd_element.get_text(strip=True))
                            
            except Exception:
                pass

        # DATA AGGREGATION & INSERT
        home_avg_odds = sum(home_odds_list) / len(home_odds_list) if home_odds_list else 0
        draw_avg_odds = sum(draw_odds_list) / len(draw_odds_list) if draw_odds_list else 0
        away_avg_odds = sum(away_odds_list) / len(away_odds_list) if away_odds_list else 0

        def _get_ou(thresh, type_):
            return over_under_data.get(thresh, {}).get(type_)
        
        def _get_ah(thresh, type_):
            return asian_handicap_data.get(thresh, {}).get(type_)

        parameters = (
            match_data['home_team'], match_data['away_team'], match_data['date'], match_data['league'],
            home_goals, away_goals, None, None, 
            home_avg_odds, away_avg_odds, draw_avg_odds,
            
            # Over/Under
            _get_ou(1.5, 'over'), _get_ou(1.5, 'under'), 
            _get_ou(2.5, 'over'), _get_ou(2.5, 'under'), 
            _get_ou(3.5, 'over'), _get_ou(3.5, 'under'), 
            
            # Correct Scores
            score_data.get('0-0'), score_data.get('1-0'), score_data.get('0-1'), score_data.get('1-1'), 
            score_data.get('2-0'), score_data.get('0-2'), score_data.get('2-1'), score_data.get('1-2'), 
            score_data.get('2-2'), score_data.get('3-0'), score_data.get('0-3'), score_data.get('3-1'), 
            score_data.get('1-3'), score_data.get('3-2'), score_data.get('2-3'), score_data.get('3-3'),
            
            # Asian Handicap
            _get_ah(0, 'home'), _get_ah(0, 'away'), 
            _get_ah(0.25, 'home'), _get_ah(0.25, 'away'), 
            _get_ah(-0.25, 'home'), _get_ah(-0.25, 'away'), 
            _get_ah(0.75, 'home'), _get_ah(0.75, 'away'), 
            _get_ah(-0.75, 'home'), _get_ah(-0.75, 'away')
        )

        insert_odds_data_query = """
            INSERT IGNORE INTO odds (
                home_team, away_team, match_date, league, 
                home_goals, away_goals, home_xg, away_xg,
                home_odds, away_odds, draw_odds, 
                over_15_odds, under_15_odds, over_25_odds, under_25_odds, over_35_odds, under_35_odds, 
                s0_0_odds, s1_0_odds, s0_1_odds, s1_1_odds, s2_0_odds, s0_2_odds, s2_1_odds, s1_2_odds, s2_2_odds, s3_0_odds, s0_3_odds, s3_1_odds, s1_3_odds, s3_2_odds, s2_3_odds, s3_3_odds, 
                home_0_odds, away_0_odds, home_p025_odds, away_m025_odds, home_m025_odds, away_p025_odds, home_p075_odds, away_m075_odds, home_m075_odds, away_p075_odds
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
        DB.execute(insert_odds_data_query, parameters)

    def _update_odds_real_xg(self) -> None:
        query = """
            UPDATE odds o
            JOIN (
                SELECT
                    th.name AS home_team, 
                    ta.name AS away_team, 
                    DATE(date) AS match_date,
                    SUM(teamA_xg) AS teamA_xg, 
                    SUM(teamB_xg) AS teamB_xg 
                FROM match_general mg 
                LEFT JOIN match_detailed md ON mg.id = md.match_id 
                LEFT JOIN teams th ON th.id = mg.home_team_id 
                LEFT JOIN teams ta ON ta.id = mg.away_team_id 
                GROUP BY th.name, ta.name, date
            ) xm ON o.match_date = xm.match_date 
                AND (
                    o.home_team  = xm.home_team  
                    OR o.away_team  = xm.away_team 
                )
            SET
                o.home_xg = ROUND(xm.teamA_xg, 2), 
                o.away_xg = ROUND(xm.teamB_xg, 2)
            WHERE o.home_xg IS NULL OR o.away_xg IS NULL
        """
        DB.execute(query)

    def _click_out_ads(self, driver) -> None:
        """
        try:
            close_button = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.overlay-bookie-modal svg.cursor-pointer")))
            driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", close_button)

        except Exception as e:
            print(f"Could not find/click ad close button: {e}")
        """
        pass

    def _safe_get(self, data_dict: dict, key: str, subkey: float, default=0.0) -> float:
        try:
            return data_dict[key][subkey]
        except (KeyError, TypeError):
            return default

    def _fix_team_names_before_update(self):
        missing_xg = DB.select("""
            SELECT o.home_team, o.away_team, o.match_date, o.league
            FROM odds o
            WHERE o.home_xg IS NULL OR o.away_xg IS NULL
        """)

        for row in tqdm(missing_xg.to_dict('records'), desc="Fixing odds names", unit="match"):
            date_str = row['match_date']

            mg_match = DB.select("""
                SELECT 
                    th.name AS home_team_mg, 
                    ta.name AS away_team_mg 
                FROM match_general mg
                LEFT JOIN teams th ON th.id = mg.home_team_id
                LEFT JOIN teams ta ON ta.id = mg.away_team_id
                WHERE DATE(mg.date) = %s
                AND (th.name = %s OR ta.name = %s)
                LIMIT 1
            """, (date_str, row['home_team'], row['away_team']))

            if len(mg_match) == 0:
                continue

            mg_row = mg_match.iloc[0]

            new_home, new_away = row['home_team'], row['away_team']

            if row['home_team'] != mg_row['home_team_mg'] and row['home_team'] != mg_row['away_team_mg']:
                if row['away_team'] == mg_row['away_team_mg']:
                    new_home = mg_row['home_team_mg']
                elif row['away_team'] == mg_row['home_team_mg']:
                    new_home = mg_row['away_team_mg']

            if row['away_team'] != mg_row['home_team_mg'] and row['away_team'] != mg_row['away_team_mg']:
                if row['home_team'] == mg_row['home_team_mg']:
                    new_away = mg_row['away_team_mg']
                elif row['home_team'] == mg_row['away_team_mg']:
                    new_away = mg_row['home_team_mg']

            if new_home and new_away and (new_home != row['home_team'] or new_away != row['away_team']):
                DB.execute("""
                    UPDATE odds 
                    SET home_team = %s, away_team = %s
                    WHERE match_date = %s AND league = %s
                    AND (home_team = %s OR away_team = %s)
                """, (new_home, new_away, row['match_date'], row['league'], row['home_team'], row['away_team']))
            else:
                print(f"⚠️ Skipped updating {row['home_team']} vs {row['away_team']} ({row['match_date']}) — ambiguous or invalid match.")

# ------------------------------ Automatization ------------------------------
class GetLineupsData:
    def __init__(self, match_id: int):
        self.match_id = match_id

        self._get_lineups()

    def _get_lineups(self) -> None:
        # FIX THIS LATER
        print(f"Getting {get_match_title(self.match_id)} lineups")  

        schedule_query = """
            SELECT 
                *
            FROM schedule
            WHERE id = %s
        """
        result = DB.select(schedule_query, (self.match_id,))
        home_team_id = int(result["home_team_id"].iloc[0])
        away_team_id = int(result["away_team_id"].iloc[0])
        match_url = result['ss_url'].iloc[0]
        match_time = result['local_time'].iloc[0]
        match_time_as_time = (datetime.min + match_time).time()
        match_timestamp = int(datetime.combine(date.today(), match_time_as_time).timestamp())

        if not match_url:
            print("No match URL provided. Skipping lineup processing.")
            return

        match = re.search(r'id:(\d+)', match_url)
        if not match:
            raise ValueError("Match ID not found in URL.")
        match_id = match.group(1)

        api_url = f"https://api.sofascore.com/api/v1/event/{match_id}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/85.0.4183.121 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        gresponse = requests.get(api_url, headers=headers)

        if gresponse.status_code != 200:
            print(f"[ERROR] API request failed with status {gresponse.status_code}. Usando Selenium como fallback.")
            event_gdata = self._fetch_json_wsel(api_url)
        else:
            event_gdata = gresponse.json()

        self.referee_name = event_gdata["event"]["referee"]["name"]

        api_lineups_url = f"https://www.sofascore.com/api/v1/event/{match_id}/lineups"
        lresponse = requests.get(api_lineups_url, headers=headers)

        if lresponse.status_code != 200:
            print(f"[ERROR] API request failed with status {gresponse.status_code}. Usando Selenium como fallback.")
            event_ldata = self._fetch_json_wsel(api_lineups_url)
        else:
            event_ldata = lresponse.json()

        if not event_ldata.get("confirmed", False):
            print("Lineups are NOT confirmed. Exiting.")
            return

        lineups = {
            "home": {"starters": [], "bench": []},
            "away": {"starters": [], "bench": []},
        }

        for side in ["home", "away"]:
            team_data = event_ldata.get(side, {})
            for player_info in team_data.get("players", []):
                player_name = player_info.get("player", {}).get("name", "Unknown")
                if player_info.get("substitute", False):
                    lineups[side]["bench"].append(player_name)
                else:
                    lineups[side]["starters"].append(player_name)

        self.home_starters = lineups["home"]["starters"]
        self.home_subs = lineups["home"]["bench"]
        self.away_starters = lineups["away"]["starters"]
        self.away_subs = lineups["away"]["bench"]

        home_ids_st, home_ids_bn = match_players(home_team_id, self.home_starters + self.home_subs)
        away_ids_st, away_ids_bn = match_players(away_team_id, self.away_starters + self.away_subs)

        home_total_extracted = len(self.home_starters) + len(self.home_subs)
        away_total_extracted = len(self.away_starters) + len(self.away_subs)

        home_all_ids = home_ids_st + home_ids_bn
        away_all_ids = away_ids_st + away_ids_bn
        self.game_strength = self.get_min_strength(home_all_ids, home_total_extracted) * self.get_min_strength(away_all_ids, away_total_extracted)

        def _build_dicts(starters, bench):
            data = []
            for pid in starters:
                data.append(
                    dict(player_id=pid,
                        yellow_card=False,
                        red_card=False,
                        on_field=True,
                        bench=False)
                )
            for pid in bench:
                data.append(
                    dict(player_id=pid,
                        yellow_card=False,
                        red_card=False,
                        on_field=False,
                        bench=True)
                )
            return data
        
        self.home_players_data = _build_dicts(home_ids_st, home_ids_bn)
        self.away_players_data = _build_dicts(away_ids_st, away_ids_bn)

        send_lineup_to_db(self.home_players_data, schedule_id=self.match_id, team="home")
        send_lineup_to_db(self.away_players_data, schedule_id=self.match_id, team="away")

        sql_query = """
            UPDATE schedule_data
               SET referee_name = %s,
                   game_strength = %s,
                   current_home_goals = %s,
                   current_away_goals = %s,
                   current_period_start_timestamp = %s,
                   period = %s,
                   simulate = 1
             WHERE schedule_id = %s
        """
        DB.execute(sql_query, (self.referee_name,
                               self.game_strength,
                               0,
                               0,
                               match_timestamp,
                               "period1",
                               match_id))

    def _fetch_json_wsel(self, url):
        s = Service('chromedriver.exe')
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--ignore-certificate-errors")
        driver = webdriver.Chrome(service=s, options=options)
        driver.get(url)

        pre_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "pre")))

        pre_content = pre_element.text
        json_data = json.loads(pre_content)

        driver.quit()
        return json_data

    def _fetch_minutes(self, pids: list[int]) -> dict[int, int]:
        if not pids:
            return {}

        placeholders = ",".join(["%s"] * len(pids))
        sql = f"""
            SELECT player_id, minutes_played
            FROM   players_data
            WHERE  player_id IN ({placeholders})
        """
        df = DB.select(sql, tuple(pids))
        return dict(zip(df["player_id"], df["minutes_played"]))

    def get_min_strength(self, matched_ids: list[int], total_extracted: int) -> float:
        if total_extracted == 0:
            return 0.0

        minutes = self._fetch_minutes(matched_ids)
        total_pct = 0
        for pid in matched_ids:
            total_pct += min(minutes.get(pid, 0) / 500, 1)
        return total_pct / total_extracted

class AutoMatchInfo:
    def __init__(self, schedule_id):
        self.schedule_id = schedule_id

        print(f"Getting {get_match_title(self.schedule_id)} live info")    

        sql_query = f"""
            SELECT 
                *
            FROM schedule_data
            WHERE schedule_id = '{self.schedule_id}';
        """
        result = DB.select(sql_query)
        match_url = result['ss_url'].iloc[0]
        home_players_data = result['home_players_data'].iloc[0]
        away_players_data = result['away_players_data'].iloc[0]
        last_minute_checked = int(result['last_minute_checked'].iloc[0] or 0)
        home_subs_avail = int(result['home_n_subs_avail'].iloc[0])
        away_subs_avail = int(result['away_n_subs_avail'].iloc[0])

        match = re.search(r'id:(\d+)', match_url)
        if not match:
            raise ValueError("Match ID not found in URL.")
        match_id = match.group(1)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/85.0.4183.121 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        api_url = f"https://www.sofascore.com/api/v1/event/{match_id}"
        gresponse = requests.get(api_url, headers=headers)

        if gresponse.status_code != 200:
            print(f"[ERROR] API request failed with status {gresponse.status_code}. Usando Selenium como fallback.")
            event_gdata = self._fetch_json_wsel(api_url)
        else:
            event_gdata = gresponse.json()
        self.home_score = int(event_gdata["event"]["homeScore"]["current"])
        self.away_score = int(event_gdata["event"]["awayScore"]["current"])

        self.current_period_start_timestamp = int(event_gdata["event"]["time"]["currentPeriodStartTimestamp"])
        self.period = event_gdata.get("event", {}).get("lastPeriod")
        if self.period and self.period[-1].isdigit():
            injury_key = f"injuryTime{self.period[-1]}"
        else:
            injury_key = None
        self.period_injury_time = int(event_gdata["event"]["time"].get(injury_key)) if injury_key and event_gdata["event"]["time"].get(injury_key) is not None else None

        def _clean(txt: str) -> str:
            return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().lower()

        def _match_player_id(api_name: str, squad_names: dict[str, str]) -> str | None:
            api_name = _clean(api_name)

            if api_name in squad_names:
                return squad_names[api_name]

            best = process.extractOne(api_name, squad_names.keys(), score_cutoff=70)
            return squad_names[best[0]] if best else None

        def parse_incidents(
            incidents: list[dict],
            home_status: list[dict],
            away_status: list[dict],
            last_minute_checked: int,
            home_subs_avail: int,
            away_subs_avail: int
        ) -> tuple[list[dict], list[dict], int, int, int, int, int]:
            events = {
                "home": {"substitutions": [], "yellow_cards": [], "red_cards": []},
                "away": {"substitutions": [], "yellow_cards": [], "red_cards": []},
            }

            def _build_idx(players_status):
                return {
                    _clean(p["player_id"].split("_")[0]): p["player_id"]
                    for p in players_status
                }

            idx_home, idx_away = _build_idx(home_status), _build_idx(away_status)

            last_minute = last_minute_checked
            cnt = {
                "home": {"sub": 0, "yellow": 0, "red": 0},
                "away": {"sub": 0, "yellow": 0, "red": 0},
            }

            # ------------------------------------------------------------------------    
            for inc in incidents:
                inc_type = inc.get("incidentType")

                # we only care about substitutions & cards ---------------------------
                if inc_type not in ("substitution", "card"):
                    continue

                minute = inc.get("time", 0)
                if minute <= last_minute_checked:
                    continue

                side       = "home" if inc.get("isHome") else "away"
                squad_idx  = idx_home if side == "home" else idx_away
                squad_stat = home_status if side == "home" else away_status

                # substitutions -------------------------------------------------------
                if inc_type == "substitution":
                    cnt[side]["sub"] += 1
                    pid_in  = _match_player_id(inc["playerIn"]["name"],  squad_idx)
                    pid_out = _match_player_id(inc["playerOut"]["name"], squad_idx)

                    for pl in squad_stat:
                        if pl["player_id"] == pid_in:
                            pl.update({"bench": False, "on_field": True})
                        elif pl["player_id"] == pid_out:
                            pl.update({"bench": False, "on_field": False})

                    events[side]["substitutions"].append(
                        {"minute": minute, "in": pid_in, "out": pid_out}
                    )

                # cards ----------------------------------------------------------------
                else:  # inc_type == "card"
                    pid = _match_player_id(inc["player"]["name"], squad_idx)

                    if inc["incidentClass"] == "yellow":
                        cnt[side]["yellow"] += 1
                        events[side]["yellow_cards"].append({"minute": minute, "player": pid})
                        for pl in squad_stat:
                            if pl["player_id"] == pid:
                                pl["yellow_card"] = True

                    elif inc["incidentClass"] == "red":
                        cnt[side]["red"] += 1
                        events[side]["red_cards"].append({"minute": minute, "player": pid})
                        for pl in squad_stat:
                            if pl["player_id"] == pid:
                                pl["red_card"] = True

                # update “last_minute” ONLY for incidents we processed ---------------
                last_minute = max(last_minute, minute)

            # simulate flags ----------------------------------------------------------
            simulate_home = int(
                cnt["home"]["sub"] > 0 or cnt["home"]["red"] > 0 or cnt["home"]["yellow"] >= 2
            )
            simulate_away = int(
                cnt["away"]["sub"] > 0 or cnt["away"]["red"] > 0 or cnt["away"]["yellow"] >= 2
            )

            home_subs_avail = max(home_subs_avail - cnt["home"]["sub"], 0)
            away_subs_avail = max(away_subs_avail - cnt["away"]["sub"], 0)

            return (
                home_status,
                away_status,
                last_minute,
                simulate_home,
                simulate_away,
                home_subs_avail,
                away_subs_avail 
            )
        
        api_incidents_url = f"https://www.sofascore.com/api/v1/event/{match_id}/incidents"
        iresponse = requests.get(api_incidents_url, headers=headers)

        incidents_data = iresponse.json()["incidents"]

        upd_home, upd_away, last_min, sim_home, sim_away, home_subs_avail, away_subs_avail = parse_incidents(
            incidents_data,
            json.loads(home_players_data),
            json.loads(away_players_data),
            last_minute_checked,
            home_subs_avail,
            away_subs_avail
        )

        simulate = int(sim_home or sim_away)

        DB.execute(
            """
            UPDATE schedule_data
            SET home_players_data               = %s,
                away_players_data              = %s,
                last_minute_checked            = %s,
                simulate                       = %s,
                current_home_goals             = %s,
                current_away_goals             = %s,
                current_period_start_timestamp = %s,
                period                         = %s,
                period_injury_time             = %s,
                home_n_subs_avail              = %s,
                away_n_subs_avail              = %s
            WHERE schedule_id = %s;
            """,
            (
                json.dumps(upd_home),
                json.dumps(upd_away),
                last_min,
                simulate,
                self.home_score,
                self.away_score,
                self.current_period_start_timestamp,
                self.period,
                self.period_injury_time,
                home_subs_avail,
                away_subs_avail,
                self.schedule_id
            )
        )

    def _fetch_json_wsel(self, url):
        s = Service('chromedriver.exe')
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--ignore-certificate-errors")
        driver = webdriver.Chrome(service=s, options=options)
        driver.get(url)

        pre_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "pre")))

        pre_content = pre_element.text
        json_data = json.loads(pre_content)

        driver.quit()
        return json_data

class AutoSS:
    def __init__(self):
        active_leagues_df = DB.select("SELECT * FROM league_data WHERE is_active = 1")
        
        for league_id in tqdm(active_leagues_df["league_id"].tolist(), desc="Processing leagues"):
            league_ss_url = active_leagues_df[active_leagues_df['league_id'] == league_id]['ss_url'].values[0]

            href_list = self.get_ss_urls(league_ss_url)

            match_dict = {}

            for url in href_list:
                if "/match/" in url:
                    parts = url.split("/match/")[1].split("/")
                    if parts:
                        match = parts[0].replace("-", " ")
                        match_dict[match] = url

            missing_ssurl_games_df = DB.select(f"SELECT schedule_id, home_team_id, away_team_id FROM schedule_data WHERE league_id = {league_id} AND date >= CURRENT_DATE")

            for _, row in missing_ssurl_games_df.iterrows():
                schedule_id = int(row["schedule_id"])
                home_team = get_team_name_by_id(int(row["home_team_id"]))
                away_team = get_team_name_by_id(int(row["away_team_id"]))
                ss_url = self.get_matched_teams_url(match_dict, f"{home_team} {away_team}")

                if ss_url:
                    upd_sql = "UPDATE schedule_data SET ss_url = %s WHERE schedule_id = %s"
                    DB.execute(upd_sql, (ss_url, schedule_id))

    def get_ss_urls(self, league_ss_url):
        s = Service('chromedriver.exe')
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--ignore-certificate-errors")
        driver = webdriver.Chrome(service=s, options=options)
        driver.get(league_ss_url)

        try:
            popup_close = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".Button.RVwfR")))
            popup_close.click()
        except Exception as e:
            print("Popup not found or not clickable:", e)

        driver.execute_script("window.scrollBy(0, 100);")
        round_div = driver.find_elements(By.CSS_SELECTOR, ".Box.kiSsvW")

        href_list = []
        for div in round_div:
            anchor_tags = div.find_elements(By.TAG_NAME, "a")
            for a in anchor_tags:
                href = a.get_attribute("href")
                if href:
                    href_list.append(href)

        driver.quit()
        return href_list

    def get_matched_teams_url(self, ssdict, target_title):
        def normalize_text(text):
            text = text.lower()
            text = unicodedata.normalize('NFKD', text)
            text = ''.join(c for c in text if not unicodedata.combining(c))
            return text
        normalized_target = normalize_text(target_title)

        normalized_ssdict = {
            normalize_text(key): key for key in ssdict.keys()
        }
        
        result = process.extractOne(
            normalized_target,
            normalized_ssdict.keys(),
            scorer=fuzz.ratio,
        )

        if result is None:
            return None 
        
        match, score, _ = result

        original_match = normalized_ssdict[match]

        if score > 50:
            best_url = ssdict[original_match]
        else:
            best_url = None

        return best_url

# ------------------------------ Trading (DELETE THIS) ------------------------------
class MatchTrade:
    def __init__(self, matched_bets):
        self.matched_bets = matched_bets
        self.selections_pl = self.profit_loss(self.matched_bets)

    def profit_loss(self, matched_bets):
        selections = {"Home": 0, "Away": 0, "Draw": 0}
        for bet in matched_bets:
            if bet["Type"] == "Back":
                bet_profit = bet["Amount"]*(bet["Odds"]-1)
                bet_liability = bet["Amount"]
            else:
                bet_profit = bet["Amount"]
                bet_liability = bet["Amount"]*(bet["Odds"]-1)
            bet["Profit"] = bet_profit
            bet["Liability"] = bet_liability

        for selection in selections.keys():
            pl = 0
            for bet in matched_bets:
                if selection == bet["Selection"]:
                    if bet["Type"] == "Back":
                        pl += bet["Profit"]
                    else:
                        pl -= bet["Liability"]
                else:
                    if bet["Type"] == "Back":
                        pl -= bet["Liability"]
                    else:
                        pl += bet["Profit"]

            selections[selection] = pl
        return selections

class TWTrade:  
    def __init__(self, matched_bets):
        self.matched_bets = matched_bets
        self.selections_pl = self.profit_loss(self.matched_bets)

    def profit_loss(self, matched_bets):
        if matched_bets and matched_bets[0]["Selection"] in ["Home AH", "Away AH"]:
            outcomes = ["Home AH", "Away AH"]
        else:
            outcomes = ["Over", "Under"]
        selections = {outcome: 0 for outcome in outcomes}
        for bet in matched_bets:
            if bet["Type"] == "Back":
                bet_profit = bet["Amount"] * (bet["Odds"] - 1)
                bet_liability = bet["Amount"]
            else:
                bet_profit = bet["Amount"]
                bet_liability = bet["Amount"] * (bet["Odds"] - 1)
            bet["Profit"] = bet_profit
            bet["Liability"] = bet_liability
        for outcome in outcomes:
            pl = 0
            for bet in matched_bets:
                if bet["Selection"] == outcome:
                    if bet["Type"] == "Back":
                        pl += bet["Profit"]
                    else:
                        pl -= bet["Liability"]
                else:
                    if bet["Type"] == "Back":
                        pl -= bet["Liability"]
                    else:
                        pl += bet["Profit"]
            selections[outcome] = pl
        return selections   

class ScoreTrade:
    def __init__(self, matched_bets):
        self.matched_bets = matched_bets
        self.selections_pl = self.profit_loss(self.matched_bets)

    def profit_loss(self, matched_bets):
        selections = {key: 0 for key in ["0-0", "0-1", "0-2", "0-3", "1-0", "1-1", "1-2", "1-3", "2-0", "2-1", "2-2", "2-3", "3-0", "3-1", "3-2", "3-3", "Home Win 4+", "Away Win 4+", "Draw +4"]}
        for bet in matched_bets:
            if bet["Type"] == "Back":
                bet_profit = bet["Amount"]*(bet["Odds"]-1)
                bet_liability = bet["Amount"]
            else:
                bet_profit = bet["Amount"]
                bet_liability = bet["Amount"]*(bet["Odds"]-1)
            bet["Profit"] = bet_profit
            bet["Liability"] = bet_liability

        for selection in selections.keys():
            pl = 0
            for bet in matched_bets:
                if selection == bet["Selection"]:
                    if bet["Type"] == "Back":
                        pl += bet["Profit"]
                    else:
                        pl -= bet["Liability"]
                else:
                    if bet["Type"] == "Back":
                        pl -= bet["Liability"]
                    else:
                        pl += bet["Profit"]

            selections[selection] = pl
        return selections
    

    def dutching(self, total_stake, selections_odds):
        stakes = {}
        total_inverse_odds = sum(1/odds for odds in selections_odds.values())
        for selection, odds in selections_odds.items():
            stakes[selection] = (total_stake / total_inverse_odds) / odds
        return stakes