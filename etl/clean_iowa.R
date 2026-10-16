library(dplyr)
library(stringr)
library(readr)
library(readxl)

# Define output filepath -------------------------------------------------
out_path <- "data/processed/cleaned_iowa.csv"

# Import data ------------------------------------------------------------

in_path <- "data/raw/iowa/MASTER_PUBLICATIONS_LIST_01-30-2026.xlsx"
df_sheets <- excel_sheets(in_path)
df <- df_sheets |>
  purrr::map(
    read_xlsx,
    path = in_path,
    col_types = c("text", "text", "text", "text", "date")
  ) |>
  bind_rows()

# Clean data -------------------------------------------------------------

# variable names
cleaned_df <- df |>
  select(TITLE, `DECISION DATE`) |>
  janitor::clean_names() |>
  rename(title_author = title, date = decision_date)

# separate authors from titles where possible
cleaned_df <- cleaned_df |>
  # create indicator
  mutate(flag_author = if_else(str_detect(title_author, " \\(by .*"), 1, 0)) |>
  mutate(
    title = if_else(
      flag_author == 1,
      str_split_i(title_author, pattern = " \\(by .*", i = 1),
      title_author
    ),
    author = if_else(
      flag_author == 1,
      str_extract(title_author, pattern = " \\(by .*"),
      NA
    )
  ) |>
  # remove "BY" from author string
  mutate(
    author = str_remove(author, pattern = " \\(by "),
    author = str_remove(author, pattern = "\\)")
  ) |>
  # keep relevant variables
  select(title, author, date)

# refactor variables
cleaned_df <- cleaned_df |>
  mutate(date = lubridate::as_date(date)) |>
  arrange(title)

# Export data ------------------------------------------------------------
write_csv(cleaned_df, out_path)
