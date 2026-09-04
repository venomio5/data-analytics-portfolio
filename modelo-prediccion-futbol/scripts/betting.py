import markets.sports.soccer.scripts.core
from tqdm import tqdm
import pandas as pd
import math

def calculate_ev(probability: float, odds: float) -> float:
    if odds is None or odds <= 0:
        return -float('inf')
    return (probability * (odds - 1)) - ((1 - probability))

def implied_probability(odds: float) -> float:
    if odds is None:
        return 0
    return 1 / odds

def find_positive_ev_match_outcome_bets(home_odds, draw_odds, away_odds, market_home_odds, market_draw_odds, market_away_odds, result):    
    home_ev = calculate_ev(implied_probability(home_odds), market_home_odds)
    draw_ev = calculate_ev(implied_probability(draw_odds), market_draw_odds) 
    away_ev = calculate_ev(implied_probability(away_odds), market_away_odds)
    
    positive_bets = []
    
    if home_ev > 0:
        positive_bets.append({
            'market': "home",
            'ev': home_ev,
            'odds': home_odds,
            'market_odds': market_home_odds,
            'result': 1 if "home" == result else -1
        })
    
    if draw_ev > 0:
        positive_bets.append({
            'market': "draw", 
            'ev': draw_ev,
            'odds': draw_odds,
            'market_odds': market_draw_odds,
            'result': 1 if "draw" == result else -1
        })
    
    if away_ev > 0:
        positive_bets.append({
            'market': "away",
            'ev': away_ev,
            'odds': away_odds,
            'market_odds': market_away_odds,
            'result': 1 if "away" == result else -1
        })
    
    return positive_bets
    
def find_positive_ev_totals_bets(over_15_odds, under_15_odds, over_25_odds, under_25_odds, 
                        over_35_odds, under_35_odds, market_over_15_odds, market_under_15_odds,
                        market_over_25_odds, market_under_25_odds, market_over_35_odds, market_under_35_odds,
                        total_goals):
    
    ev_over_15 = calculate_ev(implied_probability(over_15_odds), market_over_15_odds)
    ev_under_15 = calculate_ev(implied_probability(under_15_odds), market_under_15_odds)
    ev_over_25 = calculate_ev(implied_probability(over_25_odds), market_over_25_odds)
    ev_under_25 = calculate_ev(implied_probability(under_25_odds), market_under_25_odds)
    ev_over_35 = calculate_ev(implied_probability(over_35_odds), market_over_35_odds)
    ev_under_35 = calculate_ev(implied_probability(under_35_odds), market_under_35_odds)
    
    positive_bets = []
    
    markets = [
        ("over_15", ev_over_15, over_15_odds, market_over_15_odds),
        ("under_15", ev_under_15, under_15_odds, market_under_15_odds),
        ("over_25", ev_over_25, over_25_odds, market_over_25_odds),
        ("under_25", ev_under_25, under_25_odds, market_under_25_odds),
        ("over_35", ev_over_35, over_35_odds, market_over_35_odds),
        ("under_35", ev_under_35, under_35_odds, market_under_35_odds)
    ]
    
    for market_type, ev, odds, market_odds in markets:
        if ev > 0:
            if market_type.startswith('over'):
                threshold = float(market_type.split('_')[1][:-1] + '.' + market_type.split('_')[1][-1])
                result = 1 if total_goals > threshold else -1
            else: 
                threshold = float(market_type.split('_')[1][:-1] + '.' + market_type.split('_')[1][-1])
                result = 1 if total_goals < threshold else -1
                
            positive_bets.append({
                'market': market_type,
                'ev': ev,
                'odds': odds,
                'market_odds': market_odds,
                'result': result
            })
    
    return positive_bets

def find_positive_ev_asian_handicap_bets(
    home_0_odds, away_0_odds,
    home_p025_odds, away_m025_odds,
    home_m025_odds, away_p025_odds,
    home_p075_odds, away_m075_odds,
    home_m075_odds, away_p075_odds,
    market_home_0_odds, market_away_0_odds,
    market_home_p025_odds, market_away_m025_odds,
    market_home_m025_odds, market_away_p025_odds,
    market_home_p075_odds, market_away_m075_odds,
    market_home_m075_odds, market_away_p075_odds,
    home_goals, away_goals):
    
    ev_home_0 = calculate_ev(implied_probability(home_0_odds), market_home_0_odds)
    ev_away_0 = calculate_ev(implied_probability(away_0_odds), market_away_0_odds)
    
    ev_home_p025 = calculate_ev(implied_probability(home_p025_odds), market_home_p025_odds)
    ev_away_m025 = calculate_ev(implied_probability(away_m025_odds), market_away_m025_odds)
    
    ev_home_m025 = calculate_ev(implied_probability(home_m025_odds), market_home_m025_odds)
    ev_away_p025 = calculate_ev(implied_probability(away_p025_odds), market_away_p025_odds)
    
    ev_home_p075 = calculate_ev(implied_probability(home_p075_odds), market_home_p075_odds)
    ev_away_m075 = calculate_ev(implied_probability(away_m075_odds), market_away_m075_odds)
    
    ev_home_m075 = calculate_ev(implied_probability(home_m075_odds), market_home_m075_odds)
    ev_away_p075 = calculate_ev(implied_probability(away_p075_odds), market_away_p075_odds)
    
    ah_evs = [
        ("home_0", ev_home_0, home_0_odds, market_home_0_odds),
        ("away_0", ev_away_0, away_0_odds, market_away_0_odds),
        ("home_p025", ev_home_p025, home_p025_odds, market_home_p025_odds),
        ("away_m025", ev_away_m025, away_m025_odds, market_away_m025_odds),
        ("home_m025", ev_home_m025, home_m025_odds, market_home_m025_odds),
        ("away_p025", ev_away_p025, away_p025_odds, market_away_p025_odds),
        ("home_p075", ev_home_p075, home_p075_odds, market_home_p075_odds),
        ("away_m075", ev_away_m075, away_m075_odds, market_away_m075_odds),
        ("home_m075", ev_home_m075, home_m075_odds, market_home_m075_odds),
        ("away_p075", ev_away_p075, away_p075_odds, market_away_p075_odds)
    ]
    
    positive_bets = []
    
    for market_type, ev, odds, market_odds in ah_evs:
        if ev > 0:
            result = determine_ah_result(market_type, home_goals, away_goals)
            
            positive_bets.append({
                'market': market_type,
                'ev': ev,
                'odds': odds,
                'market_odds': market_odds,
                'result': result
            })
    
    return positive_bets

def determine_ah_result(market_type, home_goals, away_goals):
    goal_diff = home_goals - away_goals
    
    if market_type == "home_0":
        if goal_diff > 0: return 1
        elif goal_diff == 0: return 0
        else: return -1
        
    elif market_type == "away_0":
        if goal_diff < 0: return 1
        elif goal_diff == 0: return 0
        else: return -1
        
    elif market_type == "home_p025":
        if goal_diff > 0: return 1
        elif goal_diff == 0: return 0.5
        else: return -1
        
    elif market_type == "away_m025":
        if goal_diff < 0: return 1
        elif goal_diff == 0: return -0.5
        else: return 0
        
    elif market_type == "home_m025":
        if goal_diff > 0: return 1
        elif goal_diff == 0: return -0.5
        else: return 0
        
    elif market_type == "away_p025":
        if goal_diff < 0: return 1
        elif goal_diff == 0: return 0.5
        else: return -1
        
    elif market_type == "home_p075":
        if goal_diff >= 0: return 1
        elif goal_diff == -1: return -0.5
        else: return -1
        
    elif market_type == "away_m075":
        if goal_diff <= -2: return 1
        elif goal_diff == -1: return 0.5
        else: return -1
        
    elif market_type == "home_m075":
        if goal_diff >= 2: return 1
        elif goal_diff == 1: return 0.5
        else: return -1
        
    elif market_type == "away_p075":
        if goal_diff <= 0: return 1
        elif goal_diff == 1: return -0.5
        else: return -1

def find_positive_ev_correct_score_bets(match_data, home_goals, away_goals):
    positive_bets = []
    
    score_lines = [
        's0_0', 's1_0', 's0_1', 's1_1', 's2_0', 's0_2', 's2_1', 's1_2', 
        's2_2', 's3_0', 's0_3', 's3_1', 's1_3', 's3_2', 's2_3', 's3_3'
    ]
    
    for score_line in score_lines:
        odds_key = f'{score_line}_odds'
        market_odds_key = f'market_{score_line}_odds'
        
        odds = match_data[odds_key]
        market_odds = match_data[market_odds_key]
        
        ev = calculate_ev(implied_probability(odds), market_odds)
        
        if ev > 0:
            actual_score = f"{home_goals}_{away_goals}"
            result = 1 if score_line == f"s{actual_score}" else -1
            
            positive_bets.append({
                'market': score_line,
                'ev': ev,
                'odds': odds,
                'market_odds': market_odds,
                'result': result
            })
    
    return positive_bets

def kelly_bet_size(odds: float, market_odds: float, max_fraction: float=0.08, fractional_kelly: float=0.5) -> float:  
    p = implied_probability(odds)
    b = market_odds - 1
    
    kelly_fraction = (p * (b + 1) - 1) / b
    kelly_fraction = float(kelly_fraction) * fractional_kelly
    kelly_fraction = min(kelly_fraction, max_fraction)

    return kelly_fraction

def calculate_payout(result: float, odds: float, bet_pct: float):
    if result == 1:
        return odds * bet_pct
    elif result == 0:
        return bet_pct
    elif result == 0.5:
        return (odds * bet_pct / 2) + (bet_pct / 2)
    elif result == -0.5:
        return bet_pct / 2
    else:
        return 0

joined_query = """
    SELECT 
        mp.*,
        o.home_goals,
        o.away_goals,
        o.home_xg,
        o.away_xg,
        o.home_odds AS market_home_odds,
        o.away_odds AS market_away_odds,
        o.draw_odds AS market_draw_odds,
        o.over_15_odds AS market_over_15_odds,
        o.under_15_odds AS market_under_15_odds,
        o.over_25_odds AS market_over_25_odds,
        o.under_25_odds AS market_under_25_odds,
        o.over_35_odds AS market_over_35_odds,
        o.under_35_odds AS market_under_35_odds,
        o.s0_0_odds AS market_s0_0_odds,
        o.s1_0_odds AS market_s1_0_odds,
        o.s0_1_odds AS market_s0_1_odds,
        o.s1_1_odds AS market_s1_1_odds,
        o.s2_0_odds AS market_s2_0_odds,
        o.s0_2_odds AS market_s0_2_odds,
        o.s2_1_odds AS market_s2_1_odds,
        o.s1_2_odds AS market_s1_2_odds,
        o.s2_2_odds AS market_s2_2_odds,
        o.s3_0_odds AS market_s3_0_odds,
        o.s0_3_odds AS market_s0_3_odds,
        o.s3_1_odds AS market_s3_1_odds,
        o.s1_3_odds AS market_s1_3_odds,
        o.s3_2_odds AS market_s3_2_odds,
        o.s2_3_odds AS market_s2_3_odds,
        o.s3_3_odds AS market_s3_3_odds,
        o.home_0_odds AS market_home_0_odds,
        o.away_0_odds AS market_away_0_odds,
        o.home_p025_odds AS market_home_p025_odds,
        o.away_m025_odds AS market_away_m025_odds,
        o.home_m025_odds AS market_home_m025_odds,
        o.away_p025_odds AS market_away_p025_odds,
        o.home_p075_odds AS market_home_p075_odds,
        o.away_m075_odds AS market_away_m075_odds,
        o.home_m075_odds AS market_home_m075_odds,
        o.away_p075_odds AS market_away_p075_odds
    FROM match_predictions mp
    INNER JOIN odds o 
        ON mp.home_team = o.home_team 
        AND mp.away_team = o.away_team 
        AND mp.match_date = o.match_date
"""

df = core.DB.select(joined_query, ())
df = df.sort_values(by="match_date", ascending=True)

betting_records = []

for match in tqdm(df.to_dict('records'), total=len(df), desc="Betting", unit="match"):
    match_title = f"{match['home_team']} vs {match['away_team']}"
    match_date = match['match_date']
    minutes_strength = match['minutes_strength']

    # Match Outcome
    match_outcome_bets = find_positive_ev_match_outcome_bets(
        home_odds=match['home_odds'],
        draw_odds=match['draw_odds'],
        away_odds=match['away_odds'],
        market_home_odds=match['market_home_odds'],
        market_draw_odds=match['market_draw_odds'], 
        market_away_odds=match['market_away_odds'],
        result="home" if match['home_goals'] > match['away_goals'] else "away" if match['home_goals'] < match['away_goals'] else "draw"
    )

    for bet in match_outcome_bets:
        bet_pct = kelly_bet_size(bet['odds'], bet['market_odds']) * minutes_strength
        profit_pct = calculate_payout(bet['result'], float(bet['market_odds']), bet_pct) - bet_pct
        
        betting_records.append({
            'Match': match_title,
            'Date': match_date,
            'Market': bet['market'],
            'Odds': bet['odds'],
            'Market Odds': bet['market_odds'],
            'EV': bet['ev'],
            'Result': bet['result'],
            'Bet Amount (%)': bet_pct,
            'Profit/Loss (%)': profit_pct,
            'minutes_strength': minutes_strength
        })

    # Totals
    totals_bets  = find_positive_ev_totals_bets(
        over_15_odds=match['over_15_odds'],
        under_15_odds=match['under_15_odds'],
        over_25_odds=match['over_25_odds'],
        under_25_odds=match['under_25_odds'],
        over_35_odds=match['over_35_odds'],
        under_35_odds=match['under_35_odds'],
        market_over_15_odds=match['market_over_15_odds'],
        market_under_15_odds=match['market_under_15_odds'],
        market_over_25_odds=match['market_over_25_odds'],
        market_under_25_odds=match['market_under_25_odds'],
        market_over_35_odds=match['market_over_35_odds'],
        market_under_35_odds=match['market_under_35_odds'],
        total_goals=match['home_goals'] + match['away_goals']
    )
    
    for bet in totals_bets:
        bet_pct = kelly_bet_size(bet['odds'], bet['market_odds']) * minutes_strength
        profit_pct = calculate_payout(bet['result'], float(bet['market_odds']), bet_pct) - bet_pct
        
        betting_records.append({
            'Match': match_title,
            'Date': match_date,
            'Market': bet['market'],
            'Odds': bet['odds'],
            'Market Odds': bet['market_odds'],
            'EV': bet['ev'],
            'Result': bet['result'],
            'Bet Amount (%)': bet_pct,
            'Profit/Loss (%)': profit_pct,
            'minutes_strength': minutes_strength
        })

    # Correct Score
    correct_score_bets = find_positive_ev_correct_score_bets(
        match_data=match,
        home_goals=match['home_goals'],
        away_goals=match['away_goals']
    )

    correct_score_bets.sort(key=lambda x: x['ev'], reverse=True)
    
    for cs_bet in correct_score_bets:
        bet_pct = kelly_bet_size(cs_bet['odds'], cs_bet['market_odds']) * minutes_strength
        profit_pct = calculate_payout(cs_bet['result'], float(cs_bet['market_odds']), bet_pct) - bet_pct

        betting_records.append({
            'Match': match_title,
            'Date': match_date,
            'Market': cs_bet['market'],
            'Odds': cs_bet['odds'],
            'Market Odds': cs_bet['market_odds'],
            'EV': cs_bet['ev'],
            'Result': cs_bet['result'],
            'Bet Amount (%)': bet_pct,
            'Profit/Loss (%)': profit_pct,
            'minutes_strength': minutes_strength
        })

    # Asian Handicap
    ah_bets  = find_positive_ev_asian_handicap_bets(
        home_0_odds=match['home_0_odds'],
        away_0_odds=match['away_0_odds'],
        home_p025_odds=match['home_p025_odds'],
        away_m025_odds=match['away_m025_odds'],
        home_m025_odds=match['home_m025_odds'],
        away_p025_odds=match['away_p025_odds'],
        home_p075_odds=match['home_p075_odds'],
        away_m075_odds=match['away_m075_odds'],
        home_m075_odds=match['home_m075_odds'],
        away_p075_odds=match['away_p075_odds'],
        market_home_0_odds=match['market_home_0_odds'],
        market_away_0_odds=match['market_away_0_odds'],
        market_home_p025_odds=match['market_home_p025_odds'],
        market_away_m025_odds=match['market_away_m025_odds'],
        market_home_m025_odds=match['market_home_m025_odds'],
        market_away_p025_odds=match['market_away_p025_odds'],
        market_home_p075_odds=match['market_home_p075_odds'],
        market_away_m075_odds=match['market_away_m075_odds'],
        market_home_m075_odds=match['market_home_m075_odds'],
        market_away_p075_odds=match['market_away_p075_odds'],
        home_goals=match['home_goals'],
        away_goals=match['away_goals']
    )

    for bet in ah_bets:
        bet_pct = kelly_bet_size(bet['odds'], bet['market_odds']) * minutes_strength
        profit_pct = calculate_payout(bet['result'], float(bet['market_odds']), bet_pct) - bet_pct
        
        betting_records.append({
            'Match': match_title,
            'Date': match_date,
            'Market': bet['market'],
            'Odds': bet['odds'],
            'Market Odds': bet['market_odds'],
            'EV': bet['ev'],
            'Result': bet['result'],
            'Bet Amount (%)': bet_pct,
            'Profit/Loss (%)': profit_pct,
            'minutes_strength': minutes_strength
        })

# Create DataFrame and save to Excel
if betting_records:
    results_df = pd.DataFrame(betting_records)
    
    # Convert numeric columns to proper types
    results_df['Market Odds'] = pd.to_numeric(results_df['Market Odds'], errors='coerce')
    results_df['Odds'] = pd.to_numeric(results_df['Odds'], errors='coerce')
    results_df['EV'] = pd.to_numeric(results_df['EV'], errors='coerce')
    results_df['Result'] = pd.to_numeric(results_df['Result'], errors='coerce')
    results_df['Bet Amount (%)'] = pd.to_numeric(results_df['Bet Amount (%)'], errors='coerce')
    results_df['Profit/Loss (%)'] = pd.to_numeric(results_df['Profit/Loss (%)'], errors='coerce')
    
    column_order = ['Match', 'Date', 'Market', 'Odds', 'Market Odds', 'EV', 
                   'Result', 'Bet Amount (%)', 'Profit/Loss (%)', 'minutes_strength']
    results_df = results_df[column_order]
    
    results_df.to_excel('betting_results.xlsx', index=False)

    print(f"Betting results saved to 'betting_results.xlsx'")
    
    # Calculate statistics by market
    print(f"\n--- Statistics by Market Type ---")
    
    # Group by market and calculate statistics
    market_stats = results_df.groupby('Market').agg({
        'Market Odds': 'mean',
        'Result': ['count', lambda x: (x > 0).sum(), lambda x: (x < 0).sum()],
        'Profit/Loss (%)': 'sum',
        'Bet Amount (%)': 'mean'
    }).round(2)
    
    # Flatten column names
    market_stats.columns = ['Avg Market Odds', 'Total Bets', 'Winning Bets', 'Losing Bets', 'Total P/L (%)', 'Avg Bet Amount (%)']
    
    # Calculate win rate and average winning market odds
    market_stats['Win Rate (%)'] = (market_stats['Winning Bets'] / market_stats['Total Bets'] * 100).round(2)
    
    # Calculate average winning market odds (only for winning bets)
    winning_bets_stats = results_df[results_df['Result'] > 0].groupby('Market')['Market Odds'].mean().round(2)
    winning_bets_stats = winning_bets_stats.fillna(0)  # Handle cases with no winning bets
    market_stats['Avg Winning Market Odds'] = winning_bets_stats
    
    # Reorder columns for better readability
    market_stats = market_stats[['Total Bets', 'Winning Bets', 'Losing Bets', 'Win Rate (%)', 
                                'Total P/L (%)', 'Avg Bet Amount (%)', 'Avg Market Odds', 'Avg Winning Market Odds']]
    
    print(market_stats)
    
    # Overall statistics
    total_bets = len(results_df)
    winning_bets = len(results_df[results_df['Result'] > 0])
    losing_bets = len(results_df[results_df['Result'] < 0])
    push_bets = len(results_df[results_df['Result'] == 0])
    total_pl = results_df['Profit/Loss (%)'].mean()
    win_rate = (winning_bets / total_bets) * 100 if total_bets > 0 else 0
    avg_market_odds = results_df['Market Odds'].mean()
    avg_bet_amount = results_df['Bet Amount (%)'].mean()
    
    print(f"\n--- Overall Statistics ---")
    print(f"Total bets placed: {total_bets}")
    print(f"Winning bets: {winning_bets}")
    print(f"Push bets: {push_bets}")
    print(f"Losing bets: {losing_bets}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Total P/L: {total_pl:.2f}%")
    print(f"Average market odds: {avg_market_odds:.2f}")
    print(f"Average bet amount: {avg_bet_amount:.2f}%")
    
else:
    print("No positive EV bets found.")

input("wait")