# Soccer Theory

Version 9

This model simulates a football (soccer) match minute by minute, using a Markov chain / Monte Carlo–style process. Each minute is driven by two **key inputs** (one per team): **Projected Goals per minute (PG/m)**. For every simulated minute, the model outputs a simple result: **Goal or No Goal**. Every change in the scoreline is stored and later used to update **in-play probabilities**, allowing the game state to evolve realistically.

In football, everything orbits around **goals**. Predicting goals per minute is **critical** because a single goal can instantly shift motivation, tactics, etc. Everything is **connected** to PG/m and the match itself reshapes it over time.

For an example on the Markov Chain / Monte Carlo–style process check out the [simulation](simulation.ipynb) notebook.

The final match view will include also the real xG made by that time, and will filter for around +- 50% for the cumulative xg from the projections, to find the most accurate matches, and get the probabilities.

*Data is acquired by FBREF, but has to be processed for how the models learn the data.*

## Calculation of Projected Goals per minute (PG/m)

So how is PG/m calculated in the first place?

### Raw Regularized Adjusted Goals (Raw RAG)

First, a **ridge regression** (linear model) is used to learn **individual players´ offensive and defensive impact** on the field. It is like a Plus/Minus stat, but smart. It learns which players consistently have more impact based on who was on the field with them.

Now one of the additions to this model is that it **has more weight on recent matches**, for up to matches for the preceding 3 years.

For an example on this model check out the [raw_rag](raw_rag.ipynb) notebook.

### Player Fatigue & Rhythm RAG

After getting the raw RAG, the players' coefficients will be adjusted based on fatigue and rhythm. **Fatigue** and **Rhythm** will be estimated by summing recent playing minutes, but discounts older matches using **exponential decay**—fast decay (3 days) for fatigue, slower decay (7 days) for rhythm. The totals are normalized against a full 90-minute match and capped at 1, giving clean starting values that reflect how tired and how “in-form” each player is right before kickoff. Then using that as a feature for a **Ridge-regularized spline model** to capture the coefficient adjustment.

For this is important to gather the players minutes played even on external matches.

Also, the multipliers should be applied to the half of the boost or penalty for the synergy pairs.

To learn more about this model check out the [fr_rag](fr_rag.ipynb) notebook.

### Contextual Team RAG

RAG is then summed up (Baseline + Individual Offensive Coeffiecient + Offensive Synergy - Opponent Individual Defensive Coefficient) to get the teams projected xG, this is called Team Raw RAG (Which already has the Fatigue & Rhythm adjustments). Then this value is added to an advanced XGBoost model, which integrates context awareness. This are the features used:

- Team Raw RAG (As baseline xG per 90 minutes)
- Team_is_home = Bool
- Elevation_dif = (stadium elevation - avg(league, team))
- Travel_dif = Team_travel - Opp_travel (Distance in km). Home vs away = 0 - 500 = -500 | Away vs Home = 500 - 0 = 500.
- Match_state (-1.5, -0.5, 0, 0.5, 1.5) - if they are losing or wining by x goals.
- Player_dif (-1.5, -0.5, 0, 0.5, 1.5) - if a team has a red card advantage or disadvantage.
- Time Segment (1, 2, 3, 4, 5, 6) - Segments for each 15-minuteth

For a test for each feature check [contextual.ipynb](contextual.ipynb) (Includes the contextual RAS as well).

## In-Game Changes in PG/m

Now, you may ask "Why going into a simulation of each minute of the game?", and the answer is: A soccer match is dynamic, losing or winning affect how players think, that affects performance. Not only that, but other things changes, and those changes the following actions. So here are the things that changes the PxG/M:

- **Game state:** Like I said, winning or losing (by 1 or more), or level. Each goal, changes the PxG/M of both teams. So the simualtions is tracking the score.
- **Lineup changes:** In here there  are two things to keep in mind: subs and red cards.

  - **[Substitutions](substitutions.ipynb)****:** The manager´s decision to sub in a player depends on the match state. Like I said, each game is different, not the same players will play every time. I need a model to make the subs based on the managers history decisions.
    - Get the 3 window minutes for each team based on historical probability.
    - Compute the number of subs each team usually makes based on history, and determine the number they realistically allowed to do in the game.
    - Distribute the allowed number of substitutions across these likely minutes.
    - At each minute, check if it's a substitution minute. If Yes – Do Substitution (Repeat this process each time a substitution minute is reached):
    - - For players currently playing (active), calculate how likely each is to be subbed out. Factors: their total coef, minutes played, and match state.
      - Randomly pick players to be subbed out based on those weights.
      - For players on the bench (inactive), calculate how likely each is to come in. Factors: their total coef, minutes played, and match state.
      - Randomly pick players to be subbed in based on those weights.
      - Remove chosen players from active, insert new ones from passive
  - **Red Cards**: Now obviously, there are a few players that are more probable to a red card, especially if already being on a yellow card. Again this is makes the game dynamic. So how will I simualte this? By:
    - Get the teams fouls per 90 minutes by getting the average of the team fouls comitted and the opponent fouls drawn.
    - Get the normalized teams fouls per 90 minutes by getting the average from the referee fouls per match, and the sum of the team and opponent fouls per 90 minutes. Then divide the teams fouls per 90 minute by the total average.
    - Multiply each normalized team fouls per minute with home and away factors, and team status (leading, trailing, level)
    - Choose on weighed  probability on who fouled, and then on weighed probability, choose between YC, RD, and None, based on referee data and player´s data.
- **Time segment:** As the game evolve, the fatigue increases, so the PxG/m differs. So at each time segment, there is a change in PxG/m: 0-15, 15-30, 30-45, 45-60, 60-75, 75-90.

## Calculation of Expected Goals per shots (xg_sh)

This is for the Markov chain model, to realistically simulate the evolution of the game with the shots and expected goals during the game. Check [simulation.ipynb](simulation.ipynb) for more details.

Now for this I will do a Raw RAS and a Contextual Team RAS. It will be the same features so no extra notebooks are needed.

## Model Checklist

- **New Season**: Update league teams.
- **Every Week**: Update league data.
- **Every Day/Hour**: Update schedule.
