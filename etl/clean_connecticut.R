library(dplyr)
library(stringr)
library(readr)

# Define output filepath -------------------------------------------------
out_path <- "data/processed/cleaned_connecticut.csv"

# Import data ------------------------------------------------------------

df <- read_csv("data/raw/connecticut/Rejected_All__1_.csv")


# Clean data -------------------------------------------------------------

# columns of interest
col_names <- c(
  "Publication Name",
  "Publication Author",
  "Review Date",
  "Publication Type",
  "Reject Reason"
)

# variable names
cleaned_df <- df |>
  select(tidyselect::any_of(col_names)) |>
  rename(
    title = `Publication Name`,
    author = `Publication Author`,
    date = `Review Date`,
    publication_type = `Publication Type`,
    rejection_reason = `Reject Reason`
  )

# remove/replace HTML or ASCII codes
# ASCII codes: https://www.ascii-code.com/
cleaned_df <- cleaned_df |>
  # remove HTML for double quotes
  mutate(across(
    .cols = everything(),
    .fns = \(x) str_remove_all(x, "&quot;|&#34;")
  )) |>
  # replace HTML with ampersand
  mutate(across(
    .cols = everything(),
    .fns = \(x) str_replace_all(x, "&amp;", "&")
  )) |>
  # replace HTML with single quote
  # note: ASCII for inverted question mark seems instead to represent single quotation
  mutate(across(
    .cols = everything(),
    .fns = \(x) str_replace_all(x, "&#39;|&#191;", "'")
  ))

# refactor variables -----------------------------------------------------
cleaned_df <- cleaned_df |>
  mutate(date = lubridate::mdy(date)) |>
  arrange(title)

# export data ------------------------------------------------------------
write_csv(cleaned_df, out_path)
