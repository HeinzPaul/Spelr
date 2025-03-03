from flask import Flask, render_template, request, session, redirect, url_for,jsonify 
import random
import os
from werkzeug.security import generate_password_hash, check_password_hash
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from flask_pymongo import PyMongo

app = Flask(__name__)

# Use MongoDB URI from Render environment variables
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.secret_key = "supersecretkey"  # Required for session storage

# Initialize MongoDB with Flask-PyMongo
mongo = PyMongo(app)
db = mongo.db  # Access the database

# Collections
collection = db["words"]
user_collection = db["users"]



from bson import ObjectId  # ✅ Import this at the top

def get_user_progress(user_id):
    user = user_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        user = {"_id": ObjectId(user_id), "level": 1, "score": 0, "mistakes": [], "streak": 0, "used_words": [],"arcadehighscore":0}
        user_collection.insert_one(user)
     # Enrich mistakes with word details
    enriched_mistakes = []
    for mistake in user["mistakes"]:
        word_details = collection.find_one({"correct_spelling": mistake["correct"]}, {"_id": 0, "meaning": 1, "phonetics": 1, "sentence": 1})
        if word_details:
            mistake.update(word_details)  # Merge word details into mistake entry
        enriched_mistakes.append(mistake)

    user["mistakes"] = enriched_mistakes
    user.setdefault("used_words", [])  # Ensure the field exists
    return user

def update_user_progress(user_id,score,level,mistakes,streak):
    user_collection.update_one({"_id": ObjectId(user_id)},{"$set":{"score":score,"level":level,"mistakes":mistakes,"streak":streak}})


def update_user_arcade_progress(user_id,arcadehighscore):
    user_collection.update_one({"_id": ObjectId(user_id)},{"$set":{"arcadehighscore":arcadehighscore}})



@app.route("/",methods=["GET","POST"])
def landing():
    return render_template("landingpage.html")

@app.route("/selectmode",methods=["GET","POST"])
def selectmode():
    return render_template("modeselection.html")
@app.route("/signup",methods=["GET","POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if user_collection.find_one({"username":username}):
            message = "Username"
            return render_template("signup.html",message = message)
        
        hashed_password = generate_password_hash(password)

        user_id = user_collection.insert_one({"username": username, "password": hashed_password,"level":1,"score":0,"mistakes":[],"streak":0,"arcadehighscore":0}).inserted_id
        session["user_id"] = str(user_id)  # ✅ Store user ID in session

        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    message ='Invalid username or password'
    if request.method =="POST":
        username = request.form["username"]
        password = request.form["password"]

        user = user_collection.find_one({"username":username})
        if user and check_password_hash(user["password"],password):
            session["user_id"] = str(user["_id"])
            session["username"] =username
            return redirect(url_for("selectmode"))
        else:
            return render_template("login.html",message = message)
        
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()  # Clears the session
    return redirect(url_for("landing"))

@app.route("/leaderboard")
def leaderboard():
    top_users = user_collection.find({}, {"username": 1, "arcadehighscore": 1, "_id": 0}).sort("arcadehighscore", -1).limit(10)  
    return render_template("leaderboard.html", users=list(top_users))


@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id", "guest")  
    user_progress = get_user_progress(user_id)
    mistakes = user_progress["mistakes"]

    # ✅ If mistakes list is empty, pass a message to the template
    message = "No mistakes recorded yet! Great job!" if not mistakes else None
    return render_template("dashboard.html", mistakes=mistakes, message=message)


@app.route("/practicemode",methods=["GET", "POST"])
def practicemode():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session.get("user_id", "guest")  
    user_progress = get_user_progress(user_id)
    
    # Get mistakes array from user progress
    mistakes = user_progress["mistakes"]

    # Initialize a temporary practice score in the session
    if "practice_score" not in session:
        session["practice_score"] = 0

    # ✅ If no mistakes, show a message
    if not mistakes:
        return render_template("practicemode.html", message="No mistakes found. You're all caught up!", word=None)

    # ✅ Select a word only if it's a GET request or session is empty
    if "word_pair" not in session or request.method == "GET":
        word_pair = random.choice(mistakes)
        session["word_pair"] = word_pair  

    word_pair = session["word_pair"]  

    if request.method == "POST":
        user_answer = request.form.get("user_spelling")

        if user_answer.lower() == word_pair["correct"].lower():
            session["result"] = "✅ Correct!"
            session["practice_score"] += 1  # ✅ Increase temporary session score
            # ✅ Remove word from mistakes in the database
            mistakes = [m for m in mistakes if not (m["wrong"] == word_pair["wrong"] and m["correct"] == word_pair["correct"])]
        else:
            session["result"] = f"❌ Oops! I'm afraid you're wrong!"

        # ✅ Update mistakes in database (but not score or level)
        update_user_progress(user_id, user_progress["score"], user_progress["level"], mistakes, user_progress["streak"])

        session.pop("word_pair", None)  
        return redirect(url_for("practicemode"))  

    result = session.pop("result", "") if not session.get("attempted") else session["result"]
    return render_template("practicemode.html", word=word_pair["wrong"], result=result, practice_score=session["practice_score"],correct=word_pair["correct"])

@app.route("/arcade", methods=["GET", "POST"])
def arcade():
    
    if "user_id" not in session:
        return redirect("/login")
        
    user_id = session.get("user_id", "guest")
    user_progress = get_user_progress(user_id)
    arcadehighscore = user_progress["arcadehighscore"]
        
    # Initialize arcade score and streak
    session.setdefault("arcade_score", 0)
    session.setdefault("arcade_streak", 0)
    
    # Get message if exists
   
    # Determine which levels to fetch based on current score
    if session["arcade_score"] < 30:
        # Score is less than 30, fetch only words from levels 1-3
        query = {"level": {"$lte": 3}}
    else:
        # Score is 30 or higher, fetch only words from levels 4 and above
        query = {"level": {"$gt": 3}}
        
    # Fetch words from the database based on the score-dependent query
    word_list = list(collection.find(
        query,
        {'_id': 0, 'word': 1, 'correct_spelling': 1, "meaning": 1, "level": 1}
    ))
        
    # If no words exist, prevent crashing
    if not word_list:
        return "No words available at the current difficulty level!"
        
    # Select a word only if `word_list` is not empty
    if "word_pair" not in session or request.method == "GET":
        session["word_pair"] = random.choice(word_list)
        
    word_pair = session["word_pair"]
        
    if request.method == "POST":
        user_answer = request.form.get("user_spelling", "").strip()
                
        if user_answer.lower() == word_pair["correct_spelling"].lower():
            session["result"] = "✅ Correct!"
            session["arcade_score"] += 1
            session["arcade_streak"] += 1
            
        else:
            session["result"] = ""

            message = "Almost there! Keep practicing and give it another shot!"
            if arcadehighscore == 0:
                arcadehighscore = session["arcade_score"]
            elif arcadehighscore < session["arcade_score"]:
                arcadehighscore = session["arcade_score"]
                
            update_user_arcade_progress(user_id,arcadehighscore)
            # Reset both score and streak on incorrect answer
            session["arcade_score"] = 0
            session["arcade_streak"] = 0
           
            return render_template(
        "arcade.html",
        message = message,        # Pass the meaning separately
        arcadehighscore = arcadehighscore
                                )
                        
        session.pop("word_pair", None)  # Reset word selection
        return redirect(url_for("arcade"))
    
         
    result = session.pop("result", "") if "result" in session else ""
    
    # Extract meaning from word_pair if it exists
    meaning = word_pair.get("meaning", "")
    
    return render_template(
        "arcade.html",
        word=word_pair["word"],  # Show the misspelled version or hint
        meaning=meaning,         # Pass the meaning separately
        result=result,
        arcade_score=session["arcade_score"],
        streak=session["arcade_streak"]
    )

@app.route("/classic", methods=["GET", "POST"])
def classic():
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session.get("user_id", "guest")
    user_progress = get_user_progress(user_id)
    streak = user_progress["streak"]
    score = user_progress["score"]
    level = user_progress["level"]
    mistakes = user_progress["mistakes"]
    used_words = user_progress["used_words"]  

    if level == 1 and score >= 10:
        level = 2
    elif level == 2 and score >= 20:
        level = 3
    elif level == 3 and score >= 30:
        level = 4
    elif level == 4 and score >= 40:
        level = 5
    elif level == 5 and score >= 49:
        level = 6
    elif level == 6:  # ✅ Game completion condition
       return render_template("classic.html", message="Congrats!", score=score, level=level, result=session.get("result", ""), streak=streak)  # ✅ Redirects to a completion message

    # ✅ Fetch words excluding already used words
    word_list = list(collection.find(
        {'level': level, 'correct_spelling': {'$nin': used_words}},  
        {'_id': 0, 'word': 1, 'correct_spelling': 1,
"meaning":1}
    ))

    if not word_list:  
        used_words = []
        word_list = list(collection.find(
        {'level': level, 'correct_spelling': {mistakes}},  
        {'_id': 0, 'word': 1, 'correct_spelling': 1,
"meaning":1}
    ))


    if "word_pair" not in session or request.method == "GET":
        session["word_pair"] = random.choice(word_list)

    word_pair = session["word_pair"]  

    if request.method == "POST":
        user_answer = request.form.get("user_spelling")

        if user_answer.lower() == word_pair["correct_spelling"].lower():
            session["result"] = "✅ Correct!"
            score += 1  
            streak += 1
            used_words.append(word_pair["correct_spelling"])
        else:
            session["result"] = f"❌ Wrong! The correct spelling is: {word_pair['correct_spelling']}"
            if not any( m["correct"] == word_pair["correct_spelling"] for m in mistakes):
                mistakes.append({"wrong": user_answer, "correct": word_pair["correct_spelling"]})
            streak = 0

        # ✅ Add word to used_words list and update database
        
        update_user_progress(user_id, score, level, mistakes, streak)
        user_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"used_words": used_words}})

        session.pop("word_pair", None)  
        return redirect(url_for("classic"))

    return render_template("classic.html", word=word_pair["word"], score=score, level=level, result=session.get("result", ""), streak=streak,meaning = word_pair["meaning"],correct = word_pair["correct_spelling"])


if __name__ == "__main__":
    app.run(debug=True)
