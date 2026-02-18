from bs4 import BeautifulSoup
from enum import Enum
from collections import defaultdict
from statistics import mean
import requests
import json
import time

class RatingGrowth(Enum):
    EXPLOSIVE = ">400"
    VERY_HIGH = ">300"
    HIGH = ">150"
    MODERATE = ">75"
    NEUTRAL = "0"
    SLIGHT_DECLINE = ">-75"
    DECLINE = ">-150"
    STEEP_DECLINE = ">-300"


def classify_rating_growth(growth):
    if growth > 400:
        return RatingGrowth.EXPLOSIVE
    elif growth > 300:
        return RatingGrowth.VERY_HIGH
    elif growth > 150:
        return RatingGrowth.HIGH
    elif growth > 75:
        return RatingGrowth.MODERATE
    elif growth >= 0:
        return RatingGrowth.NEUTRAL
    elif growth >= -75:
        return RatingGrowth.SLIGHT_DECLINE
    elif growth >= -150:
        return RatingGrowth.DECLINE
    else:
        return RatingGrowth.STEEP_DECLINE


SNAPSHOTS = []
USER_SUBMISSIONS = defaultdict(list) 

def fetch_api(url, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            return json.loads(response.text)['result']
        except (requests.exceptions.RequestException, KeyError) as e:
            if attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

def add_user_submissions(username):
    status = fetch_api(f"https://codeforces.com/api/user.status?handle={username}")
    time.sleep(3)
    for submission in status:
        if submission["author"]["participantType"] == "CONTESTANT":
            continue

        submission_obj = {
            "id": submission["id"],
            "time": submission["creationTimeSeconds"],
            #"contestId": submission["problem"]["contestId"],
            "problem_index": submission["problem"]["index"],
            "type": submission["problem"]["type"],
            "tags": submission["problem"]["tags"],
            "rating": submission["problem"].get("rating", 0),
            "verdict": submission["verdict"],
            "passedTestCount": submission["passedTestCount"]
        }
        USER_SUBMISSIONS[username].append(submission_obj)



def add_snapshots(username):
    ratings = fetch_api(f"https://codeforces.com/api/user.rating?handle={username}")
    time.sleep(3)
    add_user_submissions(username)
    period = 5


    for i in range (0, len(ratings), period):
        batch = ratings[i: i+period]
        rating_growth = 0
        start_time = float("inf")
        end_time = 0
        rating_at_t = batch[0]['oldRating']
        for rating in batch:
            rating_growth += rating['newRating'] - rating['oldRating']
            start_time = min(start_time, rating['ratingUpdateTimeSeconds'])
            end_time = max(end_time, rating['ratingUpdateTimeSeconds'])
        
        submissions = USER_SUBMISSIONS[username]
        last_30 = sorted(
            [s for s in submissions if s["time"] <= start_time],
            key=lambda s: s["time"],
            reverse=True
        )[:30]

        snapshot = {
            "rating_at_t": rating_at_t,
            "start_time": start_time,
            "end_time": end_time,
            "rating_growth": rating_growth,
            "rating_growth_class": classify_rating_growth(rating_growth),
            "problems_last_30": last_30,
        }

        features = analyze_snapshot(snapshot)
        snapshot["features"] = features
        SNAPSHOTS.append(snapshot)
    
    print("Snapshots added for user: ", username)
    

def compute_tag_ratios(problems):
    """Return the fraction of attempted problems per tag (multi-label: each
    problem may contribute to multiple tags)."""
    tag_counts = defaultdict(int)
    total = len(problems)
    if total == 0:
        return {}
    for p in problems:
        for tag in p["tags"]:
            tag_counts[tag] += 1
    return {tag: count / total for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])}


def analyze_snapshot(snapshot):
    problems = snapshot["problems_last_30"]
    rating_at_t = snapshot["rating_at_t"]

    accepted = [p for p in problems if p["verdict"] == "OK"]
    ratings = [p["rating"] for p in accepted if p["rating"] > 0]

    # Tag ratios across all attempted problems and accepted-only problems
    all_tag_ratios = compute_tag_ratios(problems)
    accepted_tag_ratios = compute_tag_ratios(accepted)

    # Rating-bucket distribution of accepted problems
    rating_buckets = {"<=800": 0, "<=1200": 0, "<=1600": 0, "<=2000": 0,
                      "<=2400": 0, "<=3000": 0, ">3000": 0}
    for r in ratings:
        if r <= 800:
            rating_buckets["<=800"] += 1
        elif r <= 1200:
            rating_buckets["<=1200"] += 1
        elif r <= 1600:
            rating_buckets["<=1600"] += 1
        elif r <= 2000:
            rating_buckets["<=2000"] += 1
        elif r <= 2400:
            rating_buckets["<=2400"] += 1
        elif r <= 3000:
            rating_buckets["<=3000"] += 1
        else:
            rating_buckets[">3000"] += 1

    total_rated = len(ratings)
    rating_bucket_ratios = {k: v / max(total_rated, 1) for k, v in rating_buckets.items()}

    features = {
        "num_attempts": len(problems),
        "num_solved": len(accepted),
        "solve_rate": len(accepted) / max(len(problems), 1),
        "avg_problem_rating": mean(ratings) if ratings else 0,
        "avg_rating_gap": mean(r - rating_at_t for r in ratings) if ratings else 0,
        "max_problem_rating": max(ratings, default=0),
        "percent_above_rating": len([r for r in ratings if r > rating_at_t]) / max(len(ratings), 1),
        "all_tag_ratios": all_tag_ratios,
        "accepted_tag_ratios": accepted_tag_ratios,
        "rating_bucket_ratios": rating_bucket_ratios,
    }

    return features
        
        
    
if __name__ == "__main__":
    TARGET_USERS = 20
    collected = []

    for page_number in range(1, 7):
        if len(collected) >= TARGET_USERS:
            break
        page_html = open(f"./data/ratings_page_{page_number}.html")
        page = BeautifulSoup(page_html.read(), 'html.parser')
        users_a_tags = page.find_all('a', class_="rated-user")
        for user in users_a_tags:
            if len(collected) >= TARGET_USERS:
                break
            href = user.get("href")
            username = href.split("/")[-1]
            collected.append(username)
            add_snapshots(username)

    output = json.dumps(
        [{**s, "rating_growth_class": s["rating_growth_class"].value} for s in SNAPSHOTS],
        indent=4
    )
    with open("./data/snapshots.json", "w") as f:
        f.write(output)
    print(f"Saved {len(SNAPSHOTS)} snapshots to ./data/snapshots.json from {len(collected)} users")



