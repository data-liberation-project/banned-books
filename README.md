# Collecting books banned in state prisons 
This repository contains data on books banned in state prison systems in states across the country, but it's more than just a repository for the data. **The Data Liberation Project needs help requesting, cleaning and examining these lists. This is our homebase for working together.**

These efforts are part of a collaboration between [MuckRock’s](https://www.muckrock.com/) [Data Liberation Project](https://www.muckrock.com/organization/data-liberation-project/#members) and [The Marshall Project](https://www.themarshallproject.org/?ref=nav), which are teaming up to uncover what books are banned in state prison systems. We’ll be updating the data that laid the groundwork for The Marshall Project’s 2023 [investigative series](https://www.themarshallproject.org/tag/banned-books), which included a [reporting toolkit](https://www.themarshallproject.org/2023/10/03/banned-books-prisons-how-to-report) that was ultimately used by dozens of local newsrooms to examine book censorship in state prisons.


## How you can get involved 

First, join [the MuckRock Slack](https://www.muckrock.com/slack/) and find your way to the #public-data-liberation-project channel if you're not already there. That's where Data Liberation Project volunteers and grass roots investigators can find each other, coordinate efforts and share ideas. 

### 1. Extracting and organizing the data 
[Through public records requests](https://www.muckrock.com/foi/mylist/?q=&status=&tags=127887&has_embargo=&has_crowdfund=&minimum_pages=&date_range_min=&date_range_max=&file_types=&search_title=), we've recently obtained banned book lists from 17 state prison systems. The challenge is that these come in a variety of formats: XML, PDF, Excel, CSV and more. That's where you come in. 

- Start by [forking this repository](https://palewi.re/docs/first-pull-request/) so that you can open a pull request later 
- Pick a state in the `data` folder that you'd like to tackle and add a file like `clean_state_name.py` to the `etl` folder. Jump into [the Slack thread about this project](https://muckrock.slack.com/archives/C07NFFUFA4C/p1773773147623749) and let us know what state you're working on. Feel free to use whichever coding language you're most comfortable with to extract the data. If the data is a PDF, you may want to try some of [the table extraction tools on DocumentCloud](https://www.documentcloud.org/add-ons/MuckRock/azure-table-extractor/). If you haven't used DocumentCloud, you can join MuckRock's DLP organization on MuckRock and DocumentCloud by asking in the Slack channel. Organize the data using the format below:

| column | type | description | required |
|--------|------|-------------|----------|
| `title` | character | Title of the book | yes |
| `author` | character | Author of the book, if given | no |
| `date` | date | Date the book was reviewed and banned, if given | no |
| `publication_type` | character | Type of media, if given | no |
| `rejection_reason` | character | Reason cited for rejecting the book, if given | no |

- In the instances where the data is already in tabular form, filtering and renaming the columns like this will be a quicker task than extracting tables from a PDF or parsing XML. 
- Once you've extracted and cleaned the data, write a new **CSV** file to `data/processed` like `cleaned_state_name.csv`
- Submit a pull request and tackle another state! Or move on to the steps below


### 2. Highlighting books of concern

Once we have more cleaned datasets, we plan on moving them into [Datasette](https://datasette.io/) so that volunteers can explore the data more and highlight books bans that are especially concerning. For now, if you are skimming through the data and want to flag any specific titles, you can add a file like `state_name_notes.md` to `documentation`.

If you have other ideas for workflows around analyzing data and flagging censored titles, start a conversation [in Slack](https://www.muckrock.com/slack/) or in GitHub issues. 

### 3. Filing more requests 
Are you more interested in filing requests than cleaning and analyzing data? You can do that too! Drop us a line [in Slack](https://www.muckrock.com/slack/). Below is a list of where different requests are at and there's many states to fill in. Some states may not centralize the list in one statewide organization, but we'd be happy for you to join our MuckRock organization and file more requests at the local level. 

#### States that we've received data from 
- California	
- Florida		
- Illinois	
- Kansas		
- Montana		
- Texas
- Connecticut	
- Georgia		
- Iowa		
- Michigan
- New Jersey	
- Virginia
- Wisconsin
- Oregon
- Missouri 
- North Carolina
- Rhode Island
- South Carolina

#### States we've requested from but haven't yet received 
- Arizona

