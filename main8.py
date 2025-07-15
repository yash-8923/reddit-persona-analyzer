import os
import re
import json
import praw
import streamlit as st
from groq import Groq
from datetime import datetime
from dotenv import load_dotenv
import tiktoken
import hashlib
import time

# Configuration
load_dotenv()
CACHE_DIR = "reddit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
MAX_TOKENS = 7000 # Increased for potentially more context
MAX_ITEM_TOKENS = 300 # Increased to allow more content per item before truncation
MAX_ITEMS_FETCH = 20 # Increased the number of items fetched from Reddit
SUMMARIZATION_THRESHOLD = 300
REQUEST_DELAY = 1.5

# Initialize APIs
def init_apis():
    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT")
    )
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return reddit, groq_client

# Token counter using tiktoken
def count_tokens(text):
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))

# Efficient content truncation
def smart_truncate(content, max_tokens):
    if count_tokens(content) <= max_tokens:
        return content
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(content)
    
    # Try to keep start and end, with a small middle section for context if available
    # Adjusting percentages slightly
    keep_start_percent = 0.45
    keep_end_percent = 0.45
    
    start_len = int(len(tokens) * keep_start_percent)
    end_len = int(len(tokens) * keep_end_percent)
    
    # Ensure there's space for " [...] "
    if (start_len + end_len + 5) > max_tokens: # 5 tokens for " [...] [...] "
        # If combined start/end is too large, reduce proportionally
        reduction_needed = (start_len + end_len + 5) - max_tokens
        start_len = max(0, start_len - int(reduction_needed / 2))
        end_len = max(0, end_len - int(reduction_needed / 2))

    truncated_text = enc.decode(tokens[:start_len])

    if start_len + end_len < len(tokens): # If truncation actually occurred
        truncated_text += " [...] "
        truncated_text += enc.decode(tokens[len(tokens) - end_len:])
    
    # Final check and fallback for very short truncations
    if count_tokens(truncated_text) > max_tokens:
        return enc.decode(tokens[:max_tokens]) # Fallback to simple truncation if smart fails

    return truncated_text

# Robust caching
def get_cached_data(username_or_hash, data_type="raw"):
    cache_file = f"{CACHE_DIR}/{username_or_hash}_{data_type}.json"
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)
    return None

def save_to_cache(username_or_hash, data, data_type="raw"):
    cache_file = f"{CACHE_DIR}/{username_or_hash}_{data_type}.json"
    with open(cache_file, "w") as f:
        json.dump(data, f)

# Data fetching
# Data fetching
def get_reddit_data(reddit, groq_client, username):
    raw_data = get_cached_data(username, "raw")
    if raw_data:
        st.info(f"Using cached raw data for u/{username}")
        return raw_data, True
    
    st.info(f"Fetching fresh data for u/{username}...")
    try:
        user = reddit.redditor(username)
        comments = []
        posts = []
        
        # Fetch comments
        try:
            with st.spinner("Fetching comments..."):
                for c in user.comments.new(limit=MAX_ITEMS_FETCH):
                    time.sleep(REQUEST_DELAY)
                    comments.append({
                        "raw_body": c.body,
                        "url": f"https://reddit.com{c.permalink}",
                        "created_utc": c.created_utc,
                        "type": "comment" # Add type for clarity
                    })
            st.success(f"Fetched {len(comments)} comments.")
        except Exception as e:
            st.warning(f"Partial comment fetch for u/{username}: {str(e)}")
            
        # Fetch posts
        try:
            with st.spinner("Fetching posts..."):
                for s in user.submissions.new(limit=MAX_ITEMS_FETCH // 2): # Fetch fewer posts as they can be longer
                    time.sleep(REQUEST_DELAY)
                    posts.append({
                        "title": s.title,
                        "raw_body": s.selftext if s.selftext else "[No self-text]", # Handle empty selftext
                        "url": f"https://reddit.com{s.permalink}",
                        "created_utc": s.created_utc,
                        "type": "post" # Add type for clarity
                    })
            st.success(f"Fetched {len(posts)} posts.")
        except Exception as e:
            st.warning(f"Partial post fetch for u/{username}: {str(e)}")
            
        raw_data = {"comments": comments, "posts": posts}
        save_to_cache(username, raw_data, "raw")
        return raw_data, False
    except praw.exceptions.NotFound:
        st.error(f"Error: Reddit user u/{username} does not exist.")
        return {"comments": [], "posts": []}, False # Return empty lists to allow graceful continuation
    except Exception as e:
        st.error(f"Error fetching data for u/{username}. This could be due to a private profile, API issues, or other reasons: {str(e)}. Proceeding with any available data.")
        return {"comments": [], "posts": []}, False # Return empty lists to allow graceful continuation
# Process data
def process_data(groq_client, raw_data):
    # Hash raw data for cache key, even if it's empty
    data_hash = hashlib.md5(json.dumps(raw_data, sort_keys=True).encode()).hexdigest()
    processed_data = get_cached_data(data_hash, "processed")
    if processed_data:
        st.info("Using cached processed data.")
        return processed_data, True
    
    st.info("Processing raw data...")
    citation_registry = {}
    
    # Combine and sort all items by creation time (newest first) for better context flow
    all_items = sorted(
        raw_data.get("comments", []) + raw_data.get("posts", []), # Use .get() for safety
        key=lambda x: x["created_utc"], 
        reverse=True
    )
    
    processed_comments = []
    processed_posts = []

    for idx, item in enumerate(all_items):
        citation_id = f"SRC{idx+1:03d}"  # SRC001, SRC002, etc.
        citation_registry[citation_id] = item["url"]
        
        content = ""
        if item["type"] == "comment":
            content = item["raw_body"]
            if count_tokens(content) > SUMMARIZATION_THRESHOLD:
                content = smart_truncate(content, MAX_ITEM_TOKENS)
            processed_comments.append({
                "body": content,
                "created_utc": item["created_utc"],
                "citation_id": citation_id # Add citation ID here for easier linking later
            })
        elif item["type"] == "post":
            # Combine title and body for posts
            content = f"Title: {item['title']}. Body: {item['raw_body']}"
            if count_tokens(content) > SUMMARIZATION_THRESHOLD:
                content = smart_truncate(content, MAX_ITEM_TOKENS)
            processed_posts.append({
                "title": item["title"],
                "body": content,
                "created_utc": item["created_utc"],
                "citation_id": citation_id # Add citation ID here
            })
    
    processed_data = {
        "comments": processed_comments,
        "posts": processed_posts,
        "citation_registry": citation_registry
    }
    save_to_cache(data_hash, processed_data, "processed")
    return processed_data, False

# Prepare AI input with citation IDs
def prepare_ai_input(data):
    input_str = "Below is a summary of a Reddit user's recent activity (comments and posts), ordered from newest to oldest. Each item includes a citation ID [SRCXXX] that links to the original content.\n\n"
    token_count = count_tokens(input_str)
    max_tokens = MAX_TOKENS - 800 # Reserve more tokens for LLM prompt and output

    # Combine comments and posts and sort by creation time (newest first)
    all_content_items = sorted(
        data.get("comments", []) + data.get("posts", []), # Use .get() for safety
        key=lambda x: x["created_utc"], 
        reverse=True
    )
    
    item_count = 0
    for item in all_content_items:
        # Defensive check: use .get() to avoid KeyError if 'citation_id' is somehow missing
        citation_id = item.get('citation_id', 'UNKNOWN_SRC') 
        
        entry = ""
        if "title" in item: # It's a post
            entry = f"[{citation_id}] POST ({(datetime.utcfromtimestamp(item['created_utc']).strftime('%Y-%m-%d'))}): Title: {item['title']}. Content: {item['body']}\n"
        else: # It's a comment
            entry = f"[{citation_id}] COMMENT ({(datetime.utcfromtimestamp(item['created_utc']).strftime('%Y-%m-%d'))}): {item['body']}\n"
        
        entry_tokens = count_tokens(entry)
        
        if token_count + entry_tokens > max_tokens:
            st.warning(f"Truncating user activity provided to AI due to token limits. Remaining tokens: {max_tokens - token_count}")
            break
        
        input_str += entry
        token_count += entry_tokens
        item_count += 1
        
    st.info(f"Prepared {item_count} items for AI input. Total tokens: {token_count}")
    return input_str, token_count, data["citation_registry"]

# Generate executive summary with clickable links
def generate_executive_summary(groq_client, context):
    if not context.strip(): # Check if context is effectively empty after stripping whitespace
        return "No sufficient user activity found to generate an executive summary."

    prompt = f"""
    Based on the provided Reddit user activity, create a concise EXECUTIVE SUMMARY with the following sections.
    Each claim MUST be supported by a citation using the format source.

    **CRITICAL FINDINGS**
    - [Most important risk/strength inferred from the user's activity] source
    - [Another significant finding, positive or negative] source
    
    **KEY RISK FACTORS**
    - [Top risk 1 from their online behavior/content] source
    - [Top risk 2, if applicable] source
    
    **BEHAVIORAL OVERVIEW**
    - [Key repeated behavior pattern] source
    - [Another notable behavioral characteristic] source
    
    **PERSONALITY HIGHLIGHTS**
    - [Dominant personality trait] source
    - [Another key personality characteristic] source
    
    **RECOMMENDATIONS**
    - [Action item or advice based on findings] source
    - [Another recommendation, if applicable] source
    
    Rules for output:
    1.  Strictly follow the EXACT section headings provided.
    2.  Each bullet point MUST end with the citation "source".
    3.  Only infer information directly supported by the provided Reddit activity. If no information is available for a point, state "N/A" and still provide a [source] if a source was used to infer the N/A.
    4.  Keep bullet points concise, 1-2 sentences.
    5.  Focus on the most impactful and recurring themes.
    6.  Maximum 10 bullet points total across all sections.
    7.  Be objective and factual, even if brutally honest about risks.
    8.  Do NOT invent information or citations.
    9.  When citing, ALWAYS use the literal string "[source]". NEVER output raw "[SRCXXX]" or combined IDs like "[SRC001, SRC002]".
    10. Do not omit any extra brackets or signs or special characters.
    
    Here is the user's activity:
    {context}
    """
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant", # Switched to a more capable model
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"API Error during executive summary generation: {str(e)}")
        return "An error occurred while generating the executive summary. Please try again or check API key."

# Generate comprehensive persona with all sections
def generate_comprehensive_persona(groq_client, context):
    if not context.strip(): # Check if context is effectively empty after stripping whitespace
        return "No sufficient user activity found to generate a comprehensive persona."

    prompt = f"""
    Generate a COMPREHENSIVE USER PERSONA based on the provided Reddit activity.
    Each claim MUST be supported by a citation using the format [source].
    
    # Reddit User Persona Analysis
    
    **DEMOGRAPHICS (Infer if possible, otherwise state N/A)**
    - AGE: [Value or N/A] [source]
    - OCCUPATION: [Value or N/A] [source]
    - STATUS (e.g., student, parent, single): [Value or N/A] [source]
    - LOCATION: [Value or N/A] [source]
    - ARCHETYPE (e.g., "The Tech Enthusiast", "The Community Organizer", "The Casual Lurker"): [Value or N/A] [source]
    
    ## PERSONALITY TRAITS
    - [Trait 1, e.g., Analytical, Humorous, Cynical, Supportive] [source]
    - [Trait 2] [source]
    - [Trait 3, if applicable] [source]
    
    ## BEHAVIOR & HABITS
    - [Specific online habit 1, e.g., frequent commenter, engages in debates, posts guides] [source]
    - [Specific online habit 2] [source]
    - [Specific online habit 3, if applicable] [source]
    
    ## MOTIVATIONS
    - [What drives their activity/engagement? e.g., seeking help, sharing knowledge, debating] [source]
    - [Motivation 2] [source]
    - [Motivation 3, if applicable] [source]
    
    ## GOALS & NEEDS
    - [What are they trying to achieve or find? e.g., solutions, entertainment, community] [source]
    - [Goal/Need 2] [source]
    - [Goal/Need 3, if applicable] [source]
    
    ## FRUSTRATIONS
    - [What annoys them or do they complain about? e.g., bad software, political issues, misinformation] [source]
    - [Frustration 2] [source]
    - [Frustration 3, if applicable] [source]
    
    ## COMMUNICATION STYLE
    - [How do they communicate? e.g., concise, verbose, confrontational, supportive, formal, informal] [source]
    - [Communication style 2] [source]
    
    ## ONLINE ACTIVITY PATTERNS
    - [When do they typically post/comment? e.g., mostly weekdays, late nights] [source]
    - [What subreddits/topics do they frequent?] [source]
    - [How do they interact with others? e.g., upvotes, downvotes, direct replies] [source]
    
    Rules for output:
    1.  Strictly follow the EXACT section headings and order provided.
    2.  Each bullet point MUST end with the citation "[source]".
    3.  Include 2-3 specific, distinct items per section. If information is scarce, infer based on patterns or state "N/A" with a citation if an attempt to infer was made.
    4.  Only infer information directly supported by the provided Reddit activity. Do NOT invent information or citations.
    5.  Keep bullet points concise.
    6.  The persona should be a cohesive narrative of the user.
    7.  When citing, ALWAYS use the literal string "[source]". NEVER output raw "[SRCXXX]" or combined IDs like "[SRC001, SRC002]".

    Here is the user's activity:
    {context}
    """
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant", # Switched to a more capable model
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200 # Increased max tokens for persona output
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"API Error during comprehensive persona generation: {str(e)}")
        return "An error occurred while generating the comprehensive persona. Please try again or check API key."

# Replace citation IDs with Markdown links
# Replace citation IDs with Markdown links
# Replace citation IDs with Markdown links
# Replace citation IDs with Markdown links
def replace_citations(text, citation_registry):
    """
    Replace various citation formats with clickable Markdown links.
    Handles all possible LLM output variations robustly.
    """
    import re
    
    if not citation_registry:
        return text
    
    # Get the first available URL as fallback
    fallback_url = next(iter(citation_registry.values()))
    
    # Comprehensive pattern to catch all citation variations
    # This matches any combination of brackets/parentheses around "source" (case insensitive)
    # Including typos and variations, plus bare SRC references
    citation_pattern = r'''
        (?:
            \[{1,3}\s*(?:source|sources?|src|cite|ref(?:erence)?|souce|sorce|scource)\s*\]{1,3}|
            \({1,3}\s*(?:source|sources?|src|cite|ref(?:erence)?|souce|sorce|scource)\s*\){1,3}|
            \[{1,3}\s*SRC\d{3}(?:,\s*SRC\d{3})*\s*\]{1,3}|
            \[{1,3}\s*\d+\s*\]{1,3}|
            \[{1,3}\s*UNKNOWN_SRC\s*\]{1,3}|
            \bSRC\d{3}\b  # Bare SRC references like "SRC003"
        )
        (?!\()  # Not followed by ( to avoid replacing already-formed links
    '''
    
    def replace_match(match):
        matched_text = match.group(0)
        
        # Check for SRC pattern
        src_match = re.search(r'SRC(\d{3})', matched_text)
        if src_match:
            citation_id = f"SRC{src_match.group(1)}"
            url = citation_registry.get(citation_id, fallback_url)
            return f'[source]({url})'
        
        # Check for numeric pattern
        num_match = re.search(r'\b(\d+)\b', matched_text)
        if num_match:
            num = int(num_match.group(1))
            citation_id = f"SRC{num:03d}"
            url = citation_registry.get(citation_id, fallback_url)
            return f'[source]({url})'
        
        # Default case - use fallback URL
        return f'[source]({fallback_url})'
    
    # Apply the pattern replacement
    result = re.sub(citation_pattern, replace_match, text, flags=re.IGNORECASE | re.VERBOSE)
    
    return result

# Streamlit UI
def main():
    st.set_page_config(page_title="Reddit Persona Analyzer", layout="wide")
    st.title("🔍 Comprehensive Reddit Persona Analyzer")
    st.markdown("""
        <style>
        .stButton>button {
            width: 100%;
        }
        .stProgress > div > div > div > div {
            background-color: #4CAF50; /* Green for progress bar */
        }
        </style>
        """, unsafe_allow_html=True)
    
    # Removed history initialization
    # if 'history' not in st.session_state:
    #     st.session_state.history = []
    if 'current_user' not in st.session_state:
        st.session_state.current_user = None
    
    # Main input
    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input("Enter Reddit Profile URL:", 
                            placeholder="e.g., https://www.reddit.com/user/spez",
                            key="url_input")
    with col2:
        st.write("") # Add some vertical space
        st.write("")
        generate_btn = st.button("Analyze Profile", type="primary")
    
    # Sidebar with section guide
    with st.sidebar:
        st.header("Persona Sections Guide")
        st.markdown("""
            - **Demographics**: Inferred age, occupation, status, location, archetype.
            - **Personality**: Key traits and characteristics.
            - **Behavior**: Daily online habits and routines.
            - **Motivations**: Driving forces and interests behind their actions.
            - **Goals & Needs**: Objectives and aspirations.
            - **Frustrations**: Pain points and annoyances expressed.
            - **Communication**: Their typical style and patterns of interaction.
            - **Online Activity**: Patterns of engagement, frequent subreddits, etc.
        """)
        
        st.divider()
        # Removed history display and navigation
        # st.header("Analysis History")
        # if st.session_state.history:
        #     for user in st.session_state.history:
        #         if st.button(f"u/{user}", key=f"hist_{user}"):
        #             # Set the URL input and current user, then rerun
        #             st.session_state.url_input = f"https://www.reddit.com/user/{user}"
        #             st.session_state.current_user = user
        #             st.rerun()
        # else:
        #     st.info("No analysis history yet.")
    
    if generate_btn:
        if not url:
            st.warning("Please enter a Reddit profile URL.")
            return
        if not re.match(r"https?://(?:www\.)?reddit\.com/user/[^/]+/?", url):
            st.error("Invalid URL format. Please use a format like: `https://www.reddit.com/user/Example`")
            return
        
        # Fixed username extraction
        url_cleaned = url.strip().rstrip('/')
        username = url_cleaned.split('/')[-1]
        
        # Additional validation
        if not username or username in ['user', 'www.reddit.com', 'reddit.com']:
            st.error("Could not extract username from URL. Please check the format.")
            return
            
        st.info(f"Starting analysis for u/{username}...")
        reddit, groq_client = init_apis()
        
        progress_text = "Operation in progress. Please wait."
        my_bar = st.progress(0, text=progress_text)

        try:
            my_bar.progress(10, text="Fetching raw Reddit data...")
            raw_data, raw_cache_used = get_reddit_data(reddit, groq_client, username)
            
            # Allow processing to continue even if no data is found, 
            # so the AI can state "N/A" or minimal info.
            if not raw_data or (not raw_data.get("comments", []) and not raw_data.get("posts", [])):
                st.warning(f"No recent comments or posts found for u/{username}. The persona will be minimal or state N/A where information is lacking.")
            
            my_bar.progress(40, text="Processing and structuring data...")
            processed_data, processed_cache_used = process_data(groq_client, raw_data)
            
            my_bar.progress(60, text="Preparing data for AI model...")
            ai_input, token_count, citation_registry = prepare_ai_input(processed_data)
            
            # Display cache status
            cache_status_msg = ""
            if raw_cache_used and processed_cache_used:
                cache_status_msg = "♻️ Using fully cached data."
            elif raw_cache_used:
                cache_status_msg = "🔵 Using partially cached data (raw). Processing fresh for persona."
            else:
                cache_status_msg = "🔄 Processing fresh data."
            
            st.success(cache_status_msg)
            
            my_bar.progress(70, text="Generating executive summary with AI...")
            exec_summary = generate_executive_summary(groq_client, ai_input)
            
            if exec_summary:
                final_summary = replace_citations(exec_summary, citation_registry)
                st.subheader("🚀 Executive Summary")
                st.markdown(final_summary, unsafe_allow_html=True)
            else:
                st.warning("Executive summary could not be generated.")
            
            my_bar.progress(90, text="Building comprehensive persona with AI...")
            persona = generate_comprehensive_persona(groq_client, ai_input)
            
            if persona:
                final_persona = replace_citations(persona, citation_registry)
                st.divider()
                st.subheader(f"🧑‍💻 Comprehensive Persona: u/{username}")
                st.markdown(final_persona, unsafe_allow_html=True)
                
                # Save to file
                filename = f"{username}_reddit_persona_report.txt"
                report_content = f"Reddit Persona Report for u/{username}\n\n"
                report_content += "Executive Summary\n"
                report_content += "=" * 50 + "\n"
                report_content += final_summary + "\n\n"
                report_content += "Comprehensive Persona\n"
                report_content += "=" * 50 + "\n"
                report_content += final_persona + "\n\n"
                report_content += "Source References\n"
                report_content += "=" * 50 + "\n"
                # For the report, ensure citations are listed clearly
                if citation_registry:
                    for cid, url in citation_registry.items():
                        # Use plain text format for TXT file
                        report_content += f"- source: {url} (Original ID: {cid})\n" 
                else:
                    report_content += "- No direct source references found in the analyzed content.\n"

                with open(filename, "w", encoding="utf-8") as f:
                    f.write(report_content)
                
                with open(filename, "r", encoding="utf-8") as f:
                    st.download_button("Download Full Report (.txt)", f, file_name=filename, mime="text/plain")
            else:
                st.warning("Comprehensive persona generation failed.")
            
            my_bar.progress(100, text="Analysis complete!")
            time.sleep(1) # Give user a moment to see 100%
            my_bar.empty() # Remove progress bar
            
            # Show citation registry in UI expander
            with st.expander("Expand to view all Source References", expanded=False):
                st.write("Each [source] link refers to one of the following original Reddit posts/comments:")
                if citation_registry:
                    for cid, url in citation_registry.items():
                        # Display [source](URL) in the UI expander too
                        st.markdown(f"- [source]({url}) (Original ID: {cid})")
                else:
                    st.info("No sources were used in the analysis (perhaps due to insufficient user data).")
                
        except Exception as e:
            st.error(f"An unexpected system error occurred: {str(e)}")
            my_bar.empty()

if __name__ == "__main__":
    main()