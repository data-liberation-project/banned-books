library(dplyr)
library(stringr)
library(readr)

# Define output filepath -------------------------------------------------
out_path <- "data/processed/cleaned_florida.csv"

# Import data ------------------------------------------------------------

df <- readxl::read_xlsx(
  path = "data/raw/florida/LRC_DECISIONS_2012_-_PRESENT.xlsx",
  sheet = "LRC Decisions",
  range = "B2:E25621",
  col_names = c("title_author", "review_outcome", "unknown", "date")
)

# Clean data -------------------------------------------------------------

# variable names
cleaned_df <- df |> select(title_author, date, review_outcome)

# separate authors from titles where possible
cleaned_df <- cleaned_df |>
  # create indicator
  mutate(flag_author = if_else(str_detect(title_author, "\\. BY"), 1, 0)) |>
  mutate(
    title = if_else(
      flag_author == 1,
      str_split_i(title_author, pattern = "\\ BY.*", i = 1),
      title_author
    ),
    author = if_else(
      flag_author == 1,
      str_extract(title_author, pattern = "\\ BY.*"),
      NA
    )
  ) |>
  # remove "BY" from author string
  mutate(author = str_replace(author, pattern = " BY ", replacement = "")) |>
  # remove last period from author string
  mutate(author = str_remove(author, pattern = "(?s).(?!.*.)")) |>
  # keep relevant variables
  select(title, author, date, review_outcome)

# refactor variables
cleaned_df <- cleaned_df |>
  mutate(date = lubridate::as_date(date)) |>
  arrange(title)

# Export data ------------------------------------------------------------
write_csv(cleaned_df, out_path)
