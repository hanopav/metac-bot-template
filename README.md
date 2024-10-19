# Simple Metaculus forecasting bot

This repository contains a simple forecasting for [AI Forecasting Tournament](https://www.metaculus.com/aib/). It builds on the basic bot provided by the organizers of the tournament, forecasting platform Metaculus and is actively being developed further.

## Necessary steps

You can either choose to fork or copy the repository, it is up to you.

### Installing dependencies
Make sure you have [python](https://www.python.org/downloads/) and [poetry](https://python-poetry.org/docs/#installing-with-pipx) installed (poetry is a python package manager).

Inside the terminal, go to the directory you cloned the repository into and run the following command:
```bash
poetry install
```
to install all required dependencies.

### Setting environment variables

#### Locally
Running the bot requires several environment variables. If you run the bot locally, the easiest way to set them is to create a file called `.env` in the root directory of the repository and add the variables in the following format:
```bash
METACULUS_TOKEN=1234567890 # register your bot to get a here: https://www.metaculus.com/aib/
OPENAI_API_KEY=1234567890
PERPLEXITY_API_KEY=1234567890 # optional, if you want to use perplexity.ai
```
#### Github Actions
If you want to automate running the bot using GitHub actions (which I highly recommend), you have to set the environment variables in the GitHub repository settings.
Go to (Settings -> Secrets and variables -> Actions). Set API keys as repository secrets and the tournament ID and API base URL as variables.

For this simple bot, `TOURNAMENT_ID` and `API_BASE_URL` are simply hard-coded in the script and can be changed in the code itself.

## Running the bot

To run the simple bot, execute the following command in your terminal:
```bash
poetry run python simple-forecast-bot.py
```
Make sure to set the environment variables as described above and to set the parameters in the code to your liking. In particular, to submit predictions, make sure that `submit_predictions` is set to `True`.

## Automating the bot using GitHub Actions

GitHub can automatically run code in a repository. To that end, you need to fork this repository. You also need to set the secrets and environment variables in the GitHub repository settings as explained above.

Automation is handled in the `.github/workflows/` folder.

The `pr_check.yaml` file is responsible for triggering a test run every time a pull request is made to the main branch. This is useful for development and testing.

The `daily_run_simple_bot.yaml` file runs the simple bot every day (note that since `submit_predictions` is set to `False` in the script by default, no predictions will actually be posted). The `daily_run_simple_bot.yaml` file contains various comments and explanations. You should be able to simply copy this file and modify it to run your own bot. 

## Handy improvements over the Metaculus provided template

#### Averaged predictions

I have changed the script so it calls perplexity and ChatGPT-4o five times per question, each time giving a different rationale and prediction. These predictions are averaged and the average is submitted to the Metaculus platform. This is a major and simple upgrade, as the LLMs tend to sometimes make extremely stupid predictions, which is mitigated at least partially by this approach.

#### Consolidated rationale

I have implemented a secondary call to ChatGPT-4o, which uses all the rationales and makes 4-6 bullet points from it, based on the repeated nature of the arguments and their importance to the question. This primarily leads to more readable and understandable results.

#### Perplexity API Retry mechanism and JSON to store processed questions IDs

I have implemented a simple retry call mechanism and checkpointing, which mitigates the potential of LLM APIs to timeout (in case of high demand or too many calls made to the API). I have encountered this repeatedly, especially with Perplexity. Each question submitted to Metaculus is also stored in a JSON file, which allows to skip these questions when further predicting. This is not the best implementation as it is possible that mistakes will be made and the wrong (e.g. testing) version of predictions will be submitted. This is somewhat mitigated by the loading_processed_questions flag, which is by default set to false and is to be changed to True only at the time of deployment.

#### Perplexity-supported models

It seems basic, but Perplexity in the basic Metaculus bot is using **chat** and not _online_ version, which however has massive implications. The chat version has a cutoff date sometime in autumn 2023, online is scanning for current information, which is much better suited for forecasting current events.

#### Email notification on failure/success

I am planning to travel to some places without my laptop, which is why I wanted to set up some basic way to get information on whether the automated workflow is working properly. I have used a SendGrid email API, which send me an email everytime the bot is successfully started or fails to start, so I can keep myself updated.
