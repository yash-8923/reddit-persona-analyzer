# Reddit User Persona Analyzer


## Description
This project takes as input a Reddit user's profile URL and performs the following:

1. Scrapes comments and posts created by the Redditor.
2. Builds a comprehensive User Persona based on details found on their Reddit activity.
3. Outputs the User Persona in a text file.
4. For each characteristic in the User Persona, the script cites the posts or comments used to extract the specific information.

### ♻️Caching
-This project stands out by implementing efficient `caching` to minimize Reddit API usage, which helps avoid rate limits and speeds up repeated analyses. It also includes two example profiles (`kojied` and `Hungry-Move-6603`) to demonstrate its capabilities.

### ✨Uniqueness
 This tool combines data scraping, AI-driven analysis, and user-friendly output to provide insightful Reddit user personas.

## 🛠️Features
- Fetches recent comments and posts from a Reddit user.
- Uses AI to generate an executive summary and a comprehensive user persona.
- Implements caching of Reddit data to reduce API calls and improve performance.
- Provides a downloadable text report with citations linking back to original Reddit content.
- Interactive Streamlit web interface for easy use.
- Includes example profiles for quick testing and demonstration.

## ⚙️Installation

1. Clone the repository or download the project files.
2. Ensure you have Python 3.8 or higher installed.
3. Install dependencies using pip:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with your API keys and Reddit credentials. An example `.env.example` file is included for reference:

```
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=your_user_agent
GROQ_API_KEY=your_groq_api_key
```


## Get reddit api
- You can refer to this video for getting reddit api key- https://youtu.be/0mGpBxuYmpU?si=vYplJ9AWZI1e5Nss


- Select `script mode`
- Use redirect url- `http://localhost:8080`
- You will get all `credentials`

## Usage

Run the Streamlit app with:

```bash
streamlit run main8.py
```
- This will run the project on http://localhost:8501

Enter a Reddit user profile URL (e.g., `https://www.reddit.com/user/spez`) in the input box and click "Analyze Profile". The app will fetch the user's recent posts and comments, generate a user persona, and provide a downloadable report.

You can also test the app using the included example profiles:

- https://www.reddit.com/user/kojied/
- https://www.reddit.com/user/Hungry-Move-6603/

## Project Structure

- `main8.py`: Main application script.
- `requirements.txt`: Python dependencies.
- `reddit_cache/`: Directory for cached Reddit data (JSON files).
- `*_reddit_persona_report.txt`: Generated user persona reports.
- `.env.example`: Example environment variables file for reference.

## Notes

- The cache directory stores raw and processed Reddit data to speed up repeated analyses.
- The generated reports include citations linking back to the original Reddit posts and comments.
- Ensure your Reddit API credentials and Groq API key are valid and set in the `.env` file.



