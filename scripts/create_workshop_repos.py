from __future__ import print_function

import os.path
import argparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from github import Github
from github.GithubException import UnknownObjectException

import datetime


SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SAMPLE_SPREADSHEET_ID = '1qGfDoY4YUJuZ4dGjvut37xeRdbserDUQ_DqXrTabRTY'
SAMPLE_RANGE_NAME = 'Ark1!A:AC'


def fetch_coordination_sheet():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('sheets', 'v4', credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID,
                                    range=SAMPLE_RANGE_NAME).execute()
        values = result.get('values', [])

        if not values:
            print('No data found.')
            return

        # Use first row as dict keys
        return [dict(zip(values[0], row)) for row in values[1:]]
    except HttpError as err:
        print(err)


def update_file(repo, filename, new_contents):
    old_contents = repo.get_contents(filename)
    if old_contents.decoded_content.decode() != new_contents:
        repo.update_file(old_contents.path, "update " + filename, new_contents, old_contents.sha)


def list_names(organizers, institution=None):
    return "\n".join("  - first_name: " + organizer["first_name"] +
                     ("" if institution is None else ("\n    institution: " + institution)) +
                     "\n    last_name: " + organizer["last_name"]
                     for organizer in organizers)


class WorkshopMetadata:
    def __init__(self, workshop):
        self.data = workshop
        self.repo_full_name = f"emnlp-2022/{workshop['acronym']}"
        self.organizers = [{"first_name": name.partition(" ")[0], "last_name": name.partition(" ")[2]}
                           for name in workshop["organizers"].replace(" and ", ", ").split(", ")]
        if workshop["date"] == "7 & 8 December":
            self.start_date = datetime.datetime(2022, 12, 7)
            self.end_date = datetime.datetime(2022, 12, 8)
        else:
            self.start_date = self.end_date = datetime.datetime.strptime(workshop["date"], "%d/%m/%Y")
        self.conference_details = f"""book_title: Proceedings of the {workshop["name"]} ({workshop["acronym"]})
event_name: {workshop["name"]}
cover_subtitle: Proceedings of the Workshop
anthology_venue_id: {workshop["acronym"]}
start_date: {self.start_date.strftime("%Y-%m-%d")}
end_date: {self.end_date.strftime("%Y-%m-%d")}
location: Abu Dhabi, United Arab Emirates (Hybrid)
editors:
{list_names(self.organizers)}
publisher: Association for Computational Linguistics
volume_name: 1
"""
        self.organizing_committee = f"""- members:
{list_names(self.organizers, institution='')}
  role: Organizers
"""


def get_repo(g, metadata):
    try:
        return g.get_repo(metadata.repo_full_name)
    except UnknownObjectException:
        return None


def create_repo(g, metadata):
    template_repo = g.get_repo("emnlp-2022/workshop-template")
    print(f"Create {metadata.repo_full_name}? [Y/N]", end=" ")
    if input().lower() != "y":
        return
    return template_repo.create_fork(organization="emnlp-2022")


def update_repo(g, metadata, repo):
    readme = repo.get_contents("README.md").decoded_content.decode().replace("EMNLP 2022 workshop template", metadata.data["name"])
    repo.edit(name=metadata.data["acronym"], description=metadata.data["name"],
              homepage=metadata.data["website"], private=True)
    for book_chair in metadata.data["book chair github username"].replace(" ", "").split(","):
        try:
            repo.add_to_collaborators(book_chair, "admin")
        except UnknownObjectException:
            raise ValueError(f"Unknown GitHub username: {book_chair} (for {metadata.workshop['acronym']})")
    update_file(repo, "conference_details.yml", metadata.conference_details)
    update_file(repo, "organizing_committee.yml", metadata.organizing_committee)
    update_file(repo, "README.md", readme)


def main(args):
    workshop_data = fetch_coordination_sheet()
    print("Enter GitHub access token:", end=" ")
    access_token = input()
    g = Github(access_token)
    for workshop in workshop_data:
        if not workshop["book chair github username"]:
            print(f"Book chair not set for {workshop['acronym']}, skipping")
            continue
        metadata = WorkshopMetadata(workshop)
        repo = get_repo(g, metadata)
        if repo is None:
            repo = create_repo(g, metadata)
        elif args.skip_existing:
            print(f"{metadata.repo_full_name} already exists, skipping")
            continue
        else:
            print(f"{metadata.repo_full_name} already exists, update? [Y/N]", end=" ")
            if input().lower() != "y":
                continue
        update_repo(g, metadata, repo)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create metadata and update metadata repositories on GitHub for EMNLP 2022 workshops based on the data from the coordination spreadsheet on Google Sheets.")
    parser.add_argument("-s", "--skip-existing", action="store_true", help="Only create new repositories, do not even ask about updating existing ones.")
    main(parser.parse_args())
