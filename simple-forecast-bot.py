
#!/usr/bin/env python

import json
import os
import time
import requests
from decouple import config
import datetime
import re

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core import Settings
from llama_index.llms.anthropic import Anthropic
from llama_index.llms.openai import OpenAI

# Note: To understand this code, it may be easiest to start with the `main()`
# function and read the code that is called from there.

CHECKPOINT_FILE = "processed_questions.json"
MAX_RETRIES = 3
BACKOFF_FACTOR = 2

def load_processed_questions():
    """Load the list of processed question IDs from a JSON file."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as file:
            return json.load(file)
    return []

def save_processed_question(question_id):
    """Save a processed question ID to the JSON file."""
    processed_questions = load_processed_questions()
    if question_id not in processed_questions:
        processed_questions.append(question_id)
        with open(CHECKPOINT_FILE, "w") as file:
            json.dump(processed_questions, file)

def retry_request(func, *args, **kwargs):
    """Retry mechanism to retry API requests on failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                wait_time = BACKOFF_FACTOR ** (attempt - 1)
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print("Max retries reached. Skipping this request.")
                return None

def build_prompt(
        title: str,
        description: str,
        resolution_criteria: str,
        fine_print: str,
        news_info: str | None = None
    ):
    """
    Function to build the prompt using various arguments.
    """

    prompt = f"""

You are an intelligence analyst at an important government agency tasked with
assessing open-source intelligence and reasoning about similar previous
situations to develop a probabilistic estimate for a question asked by your
superior.

Your superior is also a professional forecaster, with a strong track record of
accurate forecasts of the future. They will ask you a question, and your task
is to provide the most accurate forecast you can. To do this, you evaluate past
data and trends carefully, make use of comparison classes of similar events,
take into account base rates about how past events unfolded, and outline the
best reasons for and against any particular outcome, including how they might
mutually reinforce or rule each other out.

You know that the best forecasters, among which you aspire to be, don't just
forecast according to the "vibe" of the question, and are not afraid to assign
very low or very high probabilities if the available evidence supports this.

Think about the question in a structured way. Consider what chain of events
might need to occur for the event in question to come true, how often it has
come true in the past in similar situations, and incorporate this in your
reasoning, which you are to present in full. In your reasoning, you are
supported by a quick overview of the available information your previous
research on the topic has shown.

You can't know the future, and your superior knows that, so it is more important
 to give an honest estimate that reflects the available evidence.You do not
 hedge your uncertainty, but try to give the most likely point estimate for the
 event in question happening. Remember to make sure that your point estimate
 accurately reflects your research and analysis.
    
Your interview question is:
{title}

Background:
{description}

{resolution_criteria}

{fine_print}

"""

    if news_info:
        prompt += f"""
Your research assistant says:
{news_info}

"""


    prompt += f"""
Today is {datetime.datetime.now().strftime("%Y-%m-%d")}.

Before answering you write:
(a) The time left until the outcome to the question is known.
(b) What the outcome would be if nothing changed.
(c) What you would forecast if there was only a quarter of the time left.
(d) What you would forecast if there was 4x the time left.

You write your rationale and then the last thing you write is your final answer as: "Probability: ZZ%", 0-100
"""

    return prompt

def process_forecast_probability(forecast_text: str):
    """
    Extract the forecast probability from the forecast text and clamp it between 1 and 99.
    """
    matches = re.findall(r"(\d+)%", forecast_text)
    if matches:
        # Return the last number found before a '%'
        number = int(matches[-1])
        number = min(99, max(1, number)) # clamp the number between 1 and 99
        return number
    else:
        return None


def list_questions(base_url: str, metac_token: str, tournament_id: int, offset=0, count=30):
    """
    List questions from a specific tournament. This uses the questions
    endpoint and queries it for questions belonging to a specific tournament.

    Parameters:
    -----------
    base_url : str
        the base url of the metaculus API
    metac_token : str
        the token to use for authentication
    tournament_id : int
        the ID of the tournament to list questions from
    offset : int, optional
        the number of questions to skip. This is used for pagination. I.e. if
        offset is 0 and count is 10 then the first 10 questions are returned.
        If offset is 10 and count is 10 then the next 10 questions are returned.
    count : int, optional
        the number of questions to return

    Returns:
    --------
    json
        A list of JSON objects, each containing information for a single question
    """
    # a set of parameters to pass to the questions endpoint
    url_qparams = {
        "limit": count, # the number of questions to return
        "offset": offset, # pagination offset
        "has_group": "false",
        "order_by": "-activity", # order by activity (most recent questions first)
        "forecast_type": "binary", # only binary questions are returned
        "project": tournament_id, # only questions in the specified tournament are returned
        "status": "open", # only open questions are returned
        "format": "json", # return results in json format
        "type": "forecast", # only forecast questions are returned
        "include_description": "true", # include the description in the results
    }
    url = f"{base_url}/questions/" # url for the questions endpoint
    response = requests.get(
        url,
        headers={"Authorization": f"Token {metac_token}"},
        params=url_qparams
    )
    # you can verify what this is doing by looking at
    # https://www.metaculus.com/api2/questions/?format=json&has_group=false&limit=5&offset=0&order_by=-activity&project=3294&status=open&type=forecast
    # in the browser. The URL works as follows:
    # base_url/questions/, then a "?"" before the first url param and then a "&"
    # between additional parameters

    response.raise_for_status()
    data = json.loads(response.content)
    return data["results"]

def call_metaculus_proxy(prompt: str, metac_token: str):
    """
    Call the Metaculus proxy API to generate a completion using GPT-4o model.
    
    Parameters:
    -----------
    prompt : str
        The prompt to send to the proxy API.
    metac_token : str
        The Metaculus token to authenticate with the proxy.

    Returns:
    --------
    str
        The response content from the assistant.
    """
    url = "https://www.metaculus.com/proxy/openai/v1/chat/completions/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {metac_token}",
    }
    
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(url=url, json=payload, headers=headers)
    response.raise_for_status()  # Throw an error if the request fails
    content = response.json()["choices"][0]["message"]["content"]
    return content

def call_perplexity(query):
    """
    Make a call to the perplexity API to obtain additional information.

    Parameters:
    -----------
    query : str
        The query to pass to the perplexity API. This is the question we want to
        get information about.

    Returns:
    --------
    str
        The response from the perplexity API.
    """
    url = "https://api.perplexity.ai/chat/completions"
    api_key = config("PERPLEXITY_API_KEY", default="-")
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": "llama-3.1-sonar-huge-128k-online",
        "messages": [
            {
                "role": "system", # this is a system prompt designed to guide the perplexity assistant
                "content": """
You are an intelligence analyst tasked at an international non-governmental
organization who is tasked with providing relevant up-to-date research to your
superior, who is a superforecaster.

To be an effective analyst and great assistant, you generate a concise but
detailed rundown of the most relevant news, including if the question would
resolve Yes or No based on current information.
You do not produce forecasts yourself.
""",
            },
            {
                "role": "user", # this is the actual prompt we ask the perplexity assistant to answer
                "content": query,
            },
        ],
    }

        # Use the retry mechanism for API requests
    response = retry_request(requests.post, url, json=payload, headers=headers)
    if response is not None:
        content = response.json()["choices"][0]["message"]["content"]
        return content
    return None  # If retries failed, return None

def summarize_rationales(rationales):
    
    metac_token = config("METACULUS_TOKEN")
    # Build a prompt to summarize the rationales
    summarization_prompt = (f"Summarize the following 5 rationales into a 4 to 6 bulletpoints (for all the 5 rationales combined) with the most noteworthy information repeated in most of the rationales: \n\n" + "\n\n".join(rationales))
                    
    # Call the LLM to generate the summary
    summary_response = get_model("gpt-4o", metac_token)(summarization_prompt)
    return summary_response   

def get_model(model_name: str, metac_token: str):
    """
    Get the appropriate language model based on the provided model name.
    This uses the classes provided by the llama-index library.

    Parameters:
    -----------
    model_name :
        The name of the model to instantiate. Supported values are:
        "gpt-4o", "gpt-3.5-turbo", "anthropic", "o1-preview"

    Returns:
    --------
    Union[OpenAI, Anthropic, None]
        An instance of the specified model, or None if the model name is not recognized.

    Note:
    -----
    This function relies on environment variables for API keys. These should be
    stored in a file called ".env", which will be accessed using the
    `config` function from the decouple library.
    """
    if model_name == "gpt-4o":
        return lambda prompt: call_metaculus_proxy(prompt, metac_token)
    else:
        raise ValueError("We want to use only 'gpt-4o' via Metaculus proxy.")

    match model_name:
        case "gpt-4o":
            return OpenAI(
                api_key=config("OPENAI_API_KEY", default=""),
                model=model_name
            )
        case "gpt-3.5-turbo":
            return OpenAI(
                api_key=config("OPENAI_API_KEY", default=""),
                model=model_name
            )
        case "anthropic":
            tokenizer = Anthropic().tokenizer
            Settings.tokenizer = tokenizer
            return Anthropic(
                api_key=config("ANTHROPIC_API_KEY", default=""),
                model="claude-3-5-sonnet-20240620",
            )
        case "o1-preview":
            return OpenAI(
                api_key=config("OPENAI_API_KEY", default=""),
                model=model_name
            )

    return None

def main():
    """
    Main function to run the forecasting bot. This function accesses the questions
    for a given tournament, fetches information about them, and then uses an LLM
    to generate a forecast.
    """
    
    # Define bot parameters
    use_perplexity = True
    submit_predictions = True
    loading_processed_questions = True # Keep as False until ready for deployment - testing as True will result (with submit_prediction as True) in new questions being flagged as processed and not attempted to predict on.
    metac_token = config("METACULUS_TOKEN")
    metac_base_url = "https://www.metaculus.com/api2"
    tournament_id = 32506
    llm_model_name = "gpt-4o"
    
    all_questions = []
    offset = 0

    if loading_processed_questions:
        processed_questions = load_processed_questions()

    # Fetch all questions in batches (pagination mechanism)
    while True:
        questions = list_questions(metac_base_url, metac_token, tournament_id, offset=offset)
        
        # Debugging: Check how many questions are fetched and current offset
        print(f"Fetched {len(questions)} questions with offset {offset}")

        if len(questions) < 1:
            print("No more questions to fetch, breaking loop.")
            break

        # Update the offset to fetch the next batch of questions
        offset += len(questions)
        all_questions.extend(questions)

    # Process each question
    for question in all_questions:
        if question["id"] in processed_questions:
            print(f"Skipping question ID {question['id']} (already processed)")
            continue
        print("Forecasting ", question["id"], question["question"]["title"])

        # Get news summary from Perplexity if enabled
        news_summary = call_perplexity(question["question"]["title"]) if use_perplexity else None

        # Build prompt
        prompt = build_prompt(
            question["question"]["title"],
            question["question"]["description"],
            question["question"].get("resolution_criteria", ""),
            question["question"].get("fine_print", ""),
            news_summary,
        )

        print(f"\n\n*****\nPrompt for question {question['id']}/{question['question']['title']}:\n{prompt}\n\n")

        # Initialize variables to store predictions and rationale
        predictions = []
        rationales = []

        # Get the language model to be used based on the name
        llm_model = get_model(llm_model_name, metac_token)

        # Generate 5 predictions for each question
        for i in range(5):
            try:
                response = llm_model(prompt)
                llm_prediction = process_forecast_probability(response)
                if llm_prediction is not None:
                    predictions.append(llm_prediction)
                    print(f"Prediction from run {i+1}: {llm_prediction}%")
                rationales.append(f"Run {i+1}: {response}")

            except Exception as e:
                print(f"Error generating prediction {i+1}: {e}")
                continue

        # Check if we have collected enough predictions
        if len(predictions) < 5:
            print(f"Only {len(predictions)} predictions collected for question {question['id']}. Skipping submission.")
            continue

        # Calculate the average of the 5 predictions
        average_prediction = sum(predictions) / len(predictions)
        print(f"Average prediction for question {question['id']}: {average_prediction}%")

        # Ensure the average is a percentage (not a decimal)
        formatted_average_prediction = float(average_prediction)  # Keep it as a percentage

        if submit_predictions:
            try:
                # Post the average prediction
                post_url = f"{metac_base_url}/questions/{question['id']}/predict/"
                response = requests.post(
                    post_url,
                    json={"prediction": formatted_average_prediction / 100},  # Submit as a decimal value
                    headers={"Authorization": f"Token {metac_token}"},
                )
                response.raise_for_status()

                if len(rationales) == 5:
                # Summarize the rationales if more than one is collected
                    consolidated_rationale = summarize_rationales(rationales)

                if news_summary:
                    consolidated_rationale += "\n\nUsed the following information from Perplexity:\n\n" + news_summary

                print(f"This is the consolidated rationale: {consolidated_rationale}")

                comment_url = f"{metac_base_url}/comments/"
                response = requests.post(
                    comment_url,
                    json={
                        "comment_text": consolidated_rationale,
                        "submit_type": "N",  # Submit this as a private note
                        "include_latest_prediction": True,
                        "question": question["id"],
                    },
                    headers={"Authorization": f"Token {metac_token}"},
                )
                response.raise_for_status()

                print(f"Posted prediction and comment for question {question['id']} \n\n")

                save_processed_question(question["id"])

            except Exception as e:
                print(f"Error posting prediction or comment: {e}")

if __name__ == "__main__":
    main()