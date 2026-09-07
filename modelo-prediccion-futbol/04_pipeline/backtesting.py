import markets.sports.soccer.scripts.core as core
import pandas as pd
from datetime import datetime, timedelta
import json
import os
from tqdm import tqdm

def load_progress():
    """Load current progress from JSON file"""
    if os.path.exists('progress.json'):
        with open('progress.json', 'r') as f:
            return json.load(f)

def save_progress(progress_data, date):
    """Save progress to JSON file"""
    with open('progress.json', 'w') as f:
        json.dump(progress_data, f, indent=2)

    active_leagues_df = core.DB.select("SELECT * FROM leagues WHERE is_active = 1")
    ids_str = ','.join(map(str, active_leagues_df["id"].tolist()))
    core.DB.execute(f"UPDATE leagues SET last_updated_date = %s WHERE id IN ({ids_str})", (date,))

def save_teams_data():
    active_leagues_df = core.DB.select("SELECT * FROM leagues WHERE is_active = 1 AND to_predict = 1")

    pbar = tqdm(active_leagues_df["id"].tolist(), desc="Processing leagues", unit="league")
    for league_id in pbar:
        pbar.set_postfix({"league": core.get_league_name_by_id(league_id)})
        core.FillTeamsData(league_id)
    pbar.close()

def delete_unknown_matches():
    core.DB.execute("DELETE FROM schedule WHERE home_team_id = 1 AND away_team_id = 1")
    core.DB.execute("DELETE FROM match_general WHERE home_team_id = 1 AND away_team_id = 1")

def get_next_date(date):
    safe_date_query = """
        WITH all_appearances AS (
            SELECT home_team_id AS team_id, date 
            FROM match_general 
            WHERE date >= %s
            AND home_team_id != 1 AND away_team_id != 1
            
            UNION ALL
            
            SELECT away_team_id AS team_id, date 
            FROM match_general 
            WHERE date >= %s
            AND away_team_id != 1 AND home_team_id != 1
        ),
        ranked_appearances AS (
            SELECT 
                team_id,
                date,
                ROW_NUMBER() OVER(PARTITION BY team_id ORDER BY date ASC) as game_rank
            FROM all_appearances
        )
        SELECT 
            DATE_SUB(MIN(date), INTERVAL 1 DAY) as max_safe_date
        FROM ranked_appearances
        WHERE game_rank = 2;
        """
    safe_date = core.DB.select(safe_date_query, (date, date))
    return safe_date.iloc[0]['max_safe_date']

def update_future_leagues(date):
    following_date = get_next_date(date)
    
    update_leagues_query = """
        UPDATE leagues l
        LEFT JOIN (
            SELECT DISTINCT league_id
            FROM match_general
            WHERE date BETWEEN %s AND %s
        ) active_matches ON l.id = active_matches.league_id

        SET l.is_active = IF(active_matches.league_id IS NOT NULL, 1, 0)
        WHERE l.to_predict = 1
    """
    core.DB.execute(update_leagues_query, (date, following_date))

def update_fatigue_rhythm_for_date_range(from_date, to_date):
    """
    Updates fatigue/rhythm for all players in matches within the date range.
    This must run BEFORE ProcessData so _update_fatigue_rhythm reads correct values.
    """
    matches_query = """
        SELECT DISTINCT mg.id, mg.home_team_id, mg.away_team_id, mg.date
        FROM match_general mg
        WHERE mg.date >= %s AND mg.date < %s
    """
    matches_df = core.DB.select(matches_query, (from_date, to_date))
    
    if matches_df.empty:
        return
    
    for _, match in matches_df.iterrows():
        try:
            core.update_players_fatigue_rhythm(
                home_team_id=match['home_team_id'],
                away_team_id=match['away_team_id'],
                current_date=match['date']
            )
        except Exception as e:
            print(f"Error updating fatigue/rhythm for match {match['id']}: {e}")
            continue

def save_sim_data(id): 
    players_query = """
    SELECT home_players_data, away_players_data
    FROM schedule
    WHERE id = %s
    """
    players_result = core.DB.select(players_query, (id,))

    home_data_raw = players_result.iloc[0]['home_players_data']
    away_data_raw = players_result.iloc[0]['away_players_data']
    home_players_data = json.loads(home_data_raw)
    away_players_data = json.loads(away_data_raw)
    home_players = [p['player_id'] for p in home_players_data]
    away_players = [p['player_id'] for p in away_players_data]

    minutes_strength = core.get_minutes_strength(home_players, away_players)

    insert_query = """
    INSERT INTO match_predictions (
        match_id,
        home_team, 
        away_team, 
        match_date, 
        league, 
        proj_home_xg, 
        proj_away_xg, 
        home_odds, 
        away_odds, 
        draw_odds, 
        over_15_odds, 
        under_15_odds, 
        over_25_odds, 
        under_25_odds, 
        over_35_odds, 
        under_35_odds, 
        s0_0_odds, 
        s1_0_odds, 
        s0_1_odds, 
        s1_1_odds, 
        s2_0_odds, 
        s0_2_odds, 
        s2_1_odds, 
        s1_2_odds, 
        s2_2_odds, 
        s3_0_odds,
        s0_3_odds,
        s3_1_odds, 
        s1_3_odds, 
        s3_2_odds, 
        s2_3_odds, 
        s3_3_odds, 
        home_0_odds, 
        away_0_odds, 
        home_p025_odds, 
        away_m025_odds,
        home_m025_odds, 
        away_p025_odds,
        home_p075_odds,
        away_m075_odds,
        home_m075_odds, 
        away_p075_odds, 
        minutes_strength
    )
    WITH final_scores AS (
        SELECT
            match_id,
            home_team_id,
            away_team_id,
            date,
            home_goals,
            away_goals,
            home_goals - away_goals AS goal_diff
        FROM (
            SELECT
                sc.id AS match_id,
                si.sim_id,
                sc.home_team_id,
                sc.away_team_id,
                sc.date,
                si.home_goals,
                si.away_goals,
                si.minute,
                ROW_NUMBER() OVER (PARTITION BY sim_id ORDER BY minute DESC) as rn
            FROM simulation si
            JOIN schedule sc ON si.match_id = sc.id
            WHERE si.match_id = %s
        ) ranked
        WHERE rn = 1
    ),
    match_counts AS (
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN goal_diff > 0 THEN 1 ELSE 0 END) as home_win,
            SUM(CASE WHEN goal_diff = 0 THEN 1 ELSE 0 END) as draw,
            SUM(CASE WHEN goal_diff < 0 THEN 1 ELSE 0 END) as away_win,
            SUM(CASE WHEN goal_diff = 1 THEN 1 ELSE 0 END) as home_win_1,
            SUM(CASE WHEN goal_diff = -1 THEN 1 ELSE 0 END) as away_win_1,
            SUM(CASE WHEN goal_diff >= 2 THEN 1 ELSE 0 END) as home_win_2plus,
            SUM(CASE WHEN goal_diff <= -2 THEN 1 ELSE 0 END) as away_win_2plus,
            SUM(CASE WHEN goal_diff = 2 THEN 1 ELSE 0 END) as home_win_2,
            SUM(CASE WHEN goal_diff = -2 THEN 1 ELSE 0 END) as away_win_2
        FROM final_scores
    ) 
    SELECT
        fs.match_id,
        th.name AS home,
        ta.name AS away,
        date,
        l.name AS league,
        ROUND(AVG(fs.home_goals), 2) AS proj_home_xg,
        ROUND(AVG(fs.away_goals), 2) AS proj_away_xg,

        -- Match outcome odds...
        ROUND(1 / NULLIF(mc.home_win / mc.total, 0), 3) AS home_odds,
        ROUND(1 / NULLIF(mc.away_win / mc.total, 0), 3) AS away_odds,
        ROUND(1 / NULLIF(mc.draw / mc.total, 0), 3) AS draw_odds,
        
        -- Over/Under odds...
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) > 1.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS over_15_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) < 1.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS under_15_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) > 2.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS over_25_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) < 2.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS under_25_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) > 3.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS over_35_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN (fs.home_goals + fs.away_goals) < 3.5 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS under_35_odds,

        -- Correct score odds...
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 0 AND fs.away_goals = 0 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s0_0_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 1 AND fs.away_goals = 0 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s1_0_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 0 AND fs.away_goals = 1 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s0_1_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 1 AND fs.away_goals = 1 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s1_1_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 2 AND fs.away_goals = 0 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s2_0_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 0 AND fs.away_goals = 2 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s0_2_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 2 AND fs.away_goals = 1 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s2_1_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 1 AND fs.away_goals = 2 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s1_2_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 2 AND fs.away_goals = 2 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s2_2_odds, 
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 3 AND fs.away_goals = 0 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s3_0_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 0 AND fs.away_goals = 3 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s0_3_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 3 AND fs.away_goals = 1 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s3_1_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 1 AND fs.away_goals = 3 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s1_3_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 3 AND fs.away_goals = 2 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s3_2_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 2 AND fs.away_goals = 3 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s2_3_odds,
        ROUND(1 / NULLIF(SUM(CASE WHEN fs.home_goals = 3 AND fs.away_goals = 3 THEN 1 ELSE 0 END) / mc.total, 0), 3) AS s3_3_odds,

        -- Asian handicap odds...
        -- AH 0 (Draw No Bet)
        ROUND((mc.total - mc.draw) / NULLIF(mc.home_win, 0), 3) AS home_0_odds,
        ROUND((mc.total - mc.draw) / NULLIF(mc.away_win, 0), 3) AS away_0_odds,

        -- AH ±0.25
        ROUND((mc.total - 0.5 * mc.draw)/ NULLIF(mc.home_win + 0.5 * mc.draw, 0), 3) AS home_p025_odds,
        ROUND((mc.total - 0.5 * mc.draw) / NULLIF(mc.away_win, 0), 3) AS away_m025_odds,
        ROUND((mc.total - 0.5 * mc.draw) / NULLIF(mc.home_win, 0), 3) AS home_m025_odds,
        ROUND((mc.total - 0.5 * mc.draw) / NULLIF(mc.away_win + 0.5 * mc.draw, 0), 3) AS away_p025_odds,

        -- AH ±0.75
        ROUND((mc.total - 0.5 * mc.away_win_1) / NULLIF(mc.home_win + mc.draw, 0), 3) AS home_p075_odds,
        ROUND((mc.total - 0.5 * mc.away_win_1) / NULLIF(mc.away_win_2plus + 0.5 * mc.away_win_1, 0), 3) AS away_m075_odds,
        ROUND((mc.total - 0.5 * mc.home_win_1) / NULLIF(mc.home_win_2plus + 0.5 * mc.home_win_1, 0), 3) AS home_m075_odds,
        ROUND((mc.total - 0.5 * mc.home_win_1) / NULLIF(mc.away_win + mc.draw, 0), 3) AS away_p075_odds,

        %s AS minutes_strength

    FROM final_scores fs
    JOIN match_counts mc ON 1=1
    JOIN teams th ON th.id = fs.home_team_id
    JOIN teams ta ON ta.id = fs.away_team_id
    JOIN leagues l ON th.league_id = l.id
    GROUP BY fs.match_id, fs.home_team_id, fs.away_team_id, fs.date, th.name, ta.name, l.name, mc.total, 
            mc.home_win, mc.draw, mc.away_win, mc.home_win_1, mc.away_win_1, mc.home_win_2plus, 
            mc.away_win_2plus, mc.home_win_2, mc.away_win_2
    """
    core.DB.execute(insert_query, (id,minutes_strength))

def simulate_matches(from_date, to_date):
    existing_query = """
        SELECT DISTINCT match_id 
        FROM match_predictions 
        WHERE match_id IN (
            SELECT id FROM schedule WHERE date BETWEEN %s AND %s
        )
    """

    sch_query = """ 
        SELECT s.*
        FROM schedule s
        LEFT JOIN leagues l ON l.id = s.league_id
        WHERE s.date BETWEEN %s AND %s
        AND l.to_predict = 1
    """

    sch_df = core.DB.select(sch_query, (from_date, to_date))
    existing_df = core.DB.select(existing_query, (from_date, to_date))
    
    existing_ids = set(existing_df['match_id'].tolist())
    all_match_ids = sch_df['id'].tolist()

    matches_to_simulate = [mid for mid in all_match_ids if mid not in existing_ids]

    for sch_id in tqdm(matches_to_simulate, desc="Simulating", unit="match"):
        try:
            core.MonteCarloSim(match_id=sch_id, testing=True) 
            save_sim_data(sch_id) 
        except Exception as e:
            print(f"Error simulating match {sch_id}: {e}")
            continue

def main():
    # CHANGE THIS ACCORDINGLY
    """
    1 year of test betting: 25-26
    """
    is_new_season = False  # Check below
    """
    If true:
    1. Change leagues DB data
    2. Change season_end date in progress.json
    """
    simulate = False
    players_to_refresh = False
    progress = load_progress()
    current_date = datetime.strptime(progress["current_date"], "%Y-%m-%d").date()
    season_end = datetime.strptime(progress["season_end"], "%Y-%m-%d").date()

    # Algorithm
    if is_new_season:
        print("Starting initial setup...")
        save_teams_data()
        core.UpdateSchedule(from_date=current_date, to_date=season_end, backtesting=True)
        delete_unknown_matches()
    else:
        print("Starting data gathering...")
        
        total_days = ((season_end - current_date).days) + 1
        with tqdm(total=total_days, desc="Processing days", unit="day") as pbar:
            while current_date <= season_end:
                next_date = get_next_date(pd.to_datetime(current_date)).date()
                number_of_days_proccessed = (next_date - current_date).days
                pbar.set_description(f"Processing until {next_date}")
                
                if players_to_refresh:
                    print(f"\nLeagues reactivated and need player refresh")
                    core.ProcessData(current_date=pd.to_datetime(current_date), simulation=simulate)
                    players_to_refresh = False

                update_future_leagues(current_date + timedelta(days=number_of_days_proccessed))
                
                matches_check = core.DB.select("SELECT 1 FROM match_general WHERE date >= %s AND date < %s LIMIT 1", (current_date, next_date))

                if matches_check.empty:
                    current_date = next_date
                    progress["current_date"] = current_date.strftime('%Y-%m-%d')
                    save_progress(progress, next_date)
                    pbar.update(number_of_days_proccessed)
                    continue

                unprocessed_check = core.DB.select(
                    """
                    SELECT 1 FROM match_general mg
                    LEFT JOIN match_player_breakdown mpb ON mpb.match_id = mg.id
                    WHERE mg.date >= %s AND mg.date < %s
                    AND mpb.match_id IS NULL
                    LIMIT 1
                    """,
                    (current_date, next_date)
                )

                if unprocessed_check.empty:
                    current_date = next_date
                    progress["current_date"] = current_date.strftime('%Y-%m-%d')
                    save_progress(progress, next_date)
                    pbar.update(number_of_days_proccessed)
                    continue

                # Update fatigue/rhythm BEFORE ProcessData so _update_fatigue_rhythm reads correct values
                update_fatigue_rhythm_for_date_range(from_date=current_date, to_date=next_date)

                core.ScrapeMatchesData(to_date=next_date.strftime('%Y-%m-%d'), backtesting=True, simulate=simulate) 
                
                if simulate:
                    simulate_matches(from_date=current_date, to_date=next_date)
                    core.DB.execute("TRUNCATE TABLE simulation")

                core.ProcessData(current_date=pd.to_datetime(next_date), simulation=True) 
                core.UpdateSchedule(from_date=current_date, to_date=next_date, only_transfers=True)
                
                current_date = next_date
                progress["current_date"] = current_date.strftime('%Y-%m-%d')

                save_progress(progress, next_date)
                # raise Exception("Test")
                pbar.update(number_of_days_proccessed)

if __name__ == "__main__":
    main()