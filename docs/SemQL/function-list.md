# SemQL function list

> Source: https://semarchy.com/doc/semarchy-xdm/xdm/latest/SemQL/function-list.html
> Section: SemQL | Semarchy xDM documentation (latest)

SemQL supports an extensive set of built-in functions for PostgreSQL, Oracle, and SQL Server.

The following tables list the built-in functions available in SemQL.

## Functions for Oracle

The following functions are available when using Oracle.

| Function | Description |
|---|---|
| `ABS` | Returns the absolute value of a number. |
| `ACOS` | Returns the arc cosine of a number. The argument number must be in the range of -1 to 1, and the function returns a value in the range of 0 to pi, in radians. |
| `ADD_MONTHS` | Returns the date in the form `<date>`` plus `<integer>` months. The date argument can be a datetime value or any value that can be implicitly converted to a date. The integer argument can be an integer or any value that can be implicitly converted to an integer. |
| `ASCII` | Returns the decimal representation of the first character in the string, based on the database character set. |
| `ASCIISTR` | Converts a string (or expression that resolves to a string) to an ASCII version in the database character set. Non-ASCII characters are returned in the format `xxxx`, representing a UTF-16 code unit. |
| `ASIN` | Returns the arc sine of a number. The argument number must be in the range of -1 to 1, and the function returns a value in the range of -pi/2 to pi/2, in radians. |
| `ATAN` | Returns the arc tangent of a number. The argument number can be any real number, and the function returns a value in the range of -pi/2 to pi/2, in radians. |
| `ATAN2` | Returns the arc tangent of two numbers (number1 and number2). The function returns a value between -pi and pi, depending on the signs of the arguments, in radians. `ATAN2(n1,n2)` is equivalent to `ATAN2(n1/n2)`. |
| `BIN_TO_NUM` | Converts a bit vector to its numeric equivalent. Each argument represents a bit in the vector. This function takes as arguments any numeric data type, or any non-numeric data type that can be implicitly converted to a number. Each expression must evaluate to 0 or 1. |
| `BITAND` | Computes an `AND` operation on the bits of expression1 and expression2, both of which must resolve to non-negative integers, and return an integer. |
| `CATSEARCH` | Returns a score indicating how well a text matches one or more specified categories or classifications. |
| `CEIL` | Returns the smallest integer greater than or equal to number. |
| `CHR` | Returns the character having the binary equivalent to number as a string value in the database character set. |
| `COALESCE` | Returns the first non-null expression in the expression list. At least one expression must not be the literal `NULL`. If all occurrences of expression evaluate to null, then the function returns `NULL`. |
| `COMPOSE` | Converts a string (or expression resolving to a string) into its fully normalized Unicode form. The result is in the same character set as the input. |
| `CONCAT` | Returns string1 concatenated with string2. This function is equivalent to the concatenation operator. |
| `CONTAINS` | Returns a relevance score indicating how well a text matches the specified search criteria. |
| `CONVERT` | Converts a character string from one character set to another. |
| `COS` | Returns the cosine of number (i.e., an angle expressed in radians). |
| `COSH` | Returns the hyperbolic cosine of number. |
| `CURRENT_DATE` | Returns the current date in the session timezone, in a value in the Gregorian calendar. |
| `CURRENT_TIMESTAMP` | Returns the current date and time in the session timezone. If you omit precision, then the default is 6. |
| `DBTIMEZONE` | Returns the value of the database timezone. The return type is a timezone offset (a character type in the format '+/- HH:MM') or a timezone region name. |
| `DECODE` | Compares expression to each search value one by one. If expression is equal to a search, then it returns the corresponding result. If no match is found, then it returns default. If default is omitted, then Oracle returns null. |
| `DECOMPOSE` | Converts a string to its decomposed Unicode form. For example, an o-umlaut will be returned as "o" followed by an umlaut code point. |
| `EXP` | Returns `e` raised to the power of the given number, where `e` is approximately 2.718. The function returns a value of the same type as the argument. |
| `EXTRACT_DAY` | Extracts and returns the day component from a valid ANSI date expression. |
| `EXTRACT_HOUR` | Extracts and returns the hour component from a valid ANSI datetime expression. |
| `EXTRACT_MINUTE` | Extracts and returns the minute component from a valid ANSI datetime expression. |
| `EXTRACT_MONTH` | Extracts and returns the month component from a valid ANSI date expression. |
| `EXTRACT_SECOND` | Extracts and returns the second component from a valid ANSI datetime expression. |
| `EXTRACT_TIMEZONE_ABBR` | Extracts and returns the timezone abbreviation from a valid ANSI datetime with a timezone. |
| `EXTRACT_TIMEZONE_HOUR` | Extracts and returns the timezone hour component from a valid ANSI datetime with a timezone. |
| `EXTRACT_TIMEZONE_MINUTE` | Extracts and returns the minute of the timezone from expression, which must be a valid ANSI datetime including a timezone. |
| `EXTRACT_TIMEZONE_REGION` | Extracts and returns the region of the timezone from expression, which must be a valid ANSI datetime including a timezone. |
| `EXTRACT_YEAR` | Extracts and returns the year from expression, which must be a valid ANSI date. |
| `FLOOR` | Returns largest integer equal to or less than number. |
| `FROM_TZ` | Converts a timestamp value and a timezone to a `TIMESTAMP WITH TIMEZONE` value. `timezone_value` is a character string in the format `TZH:TZM`` or a character expression that returns a string in `TZR` with optional `TZD` format. |
| `GREATEST` | Returns the greatest of the list of one or more expressions. |
| `HEXTORAW` | Converts string containing hexadecimal digits to a raw value. |
| `INITCAP` | Returns string, with the first letter of each word in uppercase, all other letters in lowercase. Words are delimited by whitespaces or characters that are not alphanumeric. |
| `INSTR` | Searches string for substring using the input character set. The function returns an integer indicating the position of the first occurrence. Optionally, you can indicate the starting position for the search and the occurrence to search for. |
| `INSTR2` | Searches string for substring using UC2 code points. The function returns an integer indicating the position of the first occurrence. Optionally, you can indicate the starting position for the search and the occurrence to search for. |
| `INSTR4` | Searches string for substring using UC4 code points. The function returns an integer indicating the position of the first occurrence. Optionally, you can indicate the starting position for the search and the occurrence to search for. |
| `INSTRB` | Searches string for substring using bytes instead of characters. The function returns an integer indicating the position of the first occurrence. Optionally, you can indicate the starting position for the search and the occurrence to search for. |
| `INSTRC` | Searches string for substring using Unicode complete characters. The function returns an integer indicating the position of the first occurrence. Optionally, you can indicate the starting position for the search and the occurrence to search for. |
| `LAST_DAY` | Returns the date of the last day of the month that contains date. |
| `LEAST` | Returns the least of the list of expressions. |
| `LENGTH` | Returns the length of string. Length is calculated using characters as defined by the input character set. |
| `LENGTH2` | Returns the length of string. Length is calculated using characters as defined by the UC2 code point. |
| `LENGTH4` | Returns the length of string. Length is calculated using characters as defined by the UC4 code point. |
| `LENGTHB` | Returns the length of string. Length is calculated using bytes instead of characters. |
| `LENGTHC` | Returns the length of string. Length is calculated using Unicode complete characters. |
| `LN` | Returns the natural logarithm of number, where number is greater than 0. |
| `LOCALTIMESTAMP` | Returns the current date and time in the session timezone. |
| `LOG` | Returns the logarithm, base number2, of number1. The base number1 can be any positive value other than 0 or 1 and number2 can be any positive value. |
| `LOWER` | Returns char, with all letters lowercase. |
| `LPAD` | Returns expression1, left-padded to length number characters with the sequence of characters in expression2. If you do not specify expression2, then the default is a single blank. |
| `LTRIM` | Removes from the left end of string all of the characters contained in `set_of_chars`. If you do not specify `set_of_chars`, it defaults to a single blank. |
| `MATCHES` | Returns a score representing how closely a text matches the specified search criteria using fuzzy or approximate matching. |
| `MOD` | Returns the remainder of number2 divided by number1. Returns number2 if number1 is 0. |
| `MONTHS_BETWEEN` | Returns number of months between dates date1 and date2. If date1 is later than date2, then the result is positive. If date1 is earlier than date2, then the result is negative. |
| `NANVL` | If number1 is not a number (`NaN`) then `NANVL` returns number2. Otherwise, it returns number1. |
| `NCHR` | Returns the character having the binary equivalent to number as a string value in the national character set. |
| `NEW_TIME` | Returns the date and time (given in timezone 1) converted in timezone (timezone2). |
| `NEXT_DAY` | Returns the date of the first weekday named by `day_name` that is later than the date. |
| `NLSSORT` | Returns a collation key for string—​that is, a string of bytes used to sort strings. `lsparam` is in the form `NLS_SORT=sort` where sort is either `BINARY` or a linguistic sort sequence. This function manages language-specific sorting. |
| `NLS_INITCAP` | Returns string with the first letter of each word in uppercase and all other letters in lowercase. `nlsparam` is in the form `NLS_SORT=sort` where sort is either BINARY or a linguistic sort sequence. This function manages language-specific character case changes. |
| `NLS_LOWER` | Returns string with all letters in lowercase. `nlsparam` is in the form `NLS_SORT=sort` where `sort` is either `BINARY` or a linguistic sort sequence. |
| `NLS_UPPER` | Returns string with all letters in uppercase. `nlsparam` is in the form `NLS_SORT=sort` where `sort` is either `BINARY` or a linguistic sort sequence. |
| `NULLIF` | Compares expression1 and expression2. If they are equal, then the function returns null. If they are not equal, then the function returns expression1. You cannot specify the literal `NULL` for expression1. The `NULLIF` function is logically equivalent to the following `CASE` expression: `CASE WHEN expression1 = expression2 THEN NULL ELSE expression1 END`. |
| `NUMTODSINTERVAL` | Converts number to an `INTERVAL DAY TO SECOND` literal. The value for `interval_unit` specifies the unit of number and must resolve to one of the following string values: `DAY`, `HOUR`, `MINUTE`, `SECOND`. |
| `NUMTOYMINTERVAL` | Converts number to an `INTERVAL YEAR TO MONTH` literal. The value for `interval_unit` specifies the unit of number and must resolve to one of the following string values: `YEAR`, `MONTH`. |
| `NVL` | If expression1 is null, then `NVL` returns expression2. If expression1 is not null, then `NVL` returns expression1. |
| `NVL2` | If expression1 is not null, then `NVL2` returns expression2. If expression1 is null, then `NVL2` returns expr3. |
| `ORA_HASH` | Computes a hash value for a given expression. The expression argument determines the data for which you want to compute a hash value. The optional `max_bucket` argument determines the maximum bucket value returned by the hash function. You can specify any value between 0 and 4294967295. The default is 4294967295. The optional `seed_value` argument produces many different results for the same set of data. |
| `POWER` | Returns number2 raised to the number1 power. The base number2 and the exponent number1 can be any numbers, but if number2 is negative, then number1 must be an integer. |
| `RAWTOHEX` | Converts raw to a character value containing its hexadecimal equivalent. |
| `REGEXP_COUNT` | Extends the functionality of the `REGEXP_INSTR` function by returning the number of times a pattern occurs in a source string, starting at position. `match_param contains one or more of the following values: i - case-insensitive match, c - case-sensitive match, n - allow '.' to match even the newline character, m - treat input as multiple lines, x - ignore whitespaces. |
| `REGEXP_INSTR` | Extends the functionality of the `INSTR` function by letting you search a string for a regular expression pattern. It returns an integer indicating the beginning or ending position of the matched substring, depending on the value of the `return_option` argument. If no match is found, the function returns 0. `match_param` contains one or more of the following values: i - case-insensitive match, c - case-sensitive match, n - allow '.' to match even the newline character, m - treat input as multiple lines. |
| `REGEXP_REPLACE` | Extends the functionality of the `REPLACE` function by letting you search a string for a regular expression pattern. By default, the function returns `source_char` with every occurrence of the regular expression pattern replaced with `replace_string`. `match_param` contains one or more of the following values: i - case-insensitive match, c - case-sensitive match, n - allow '.' to match even the newline character, m - treat input as multiple lines. |
| `REGEXP_SUBSTR` | Extends the functionality of the `SUBSTR` function by letting you search a string for a regular expression pattern. It is also similar to `REGEXP_INSTR`, but instead of returning the position of the substring, it returns the substring itself. This function is useful if you need the contents of a match string but not its position in the source string. `match_param` contains one or more of the following values: i - case-insensitive match, c - case-sensitive match, n - allow '.' to match even the newline character, m - treat input as multiple lines. |
| `REMAINDER` | Returns the remainder of number2 divided by number1. |
| `REPLACE` | Returns string with every occurrence of `search_string` replaced with `replacement_string`. If `replacement_string` is omitted or null, then all occurrences of `search_string` are removed. If `search_string` is null, then string is returned. |
| `ROUND` | Returns `date_or_number` rounded to the unit specified by the format model `fmt_or_integer`. |
| `RPAD` | Returns expression1, right-padded to length number characters with expression2, replicated as many times as necessary. If you do not specify expression2, then it defaults to a single blank. |
| `RTRIM` | Removes from the right end of string all of the characters that appear in `set_of_chars`. If you do not specify `set_of_chars`, then it defaults to a single blank. |
| `SEM_BOOLEAN_TO_CHAR` | Converts a boolean to its standard string representation. The returned value is `true` or `false`. |
| `SEM_CONCAT` | Returns a string concatenating the input values with the separator. Set the `skip_null` parameter to '1' to skip null values. Set the `sep` parameter to an empty string '' to have no separator. |
| `SEM_EDIT_DISTANCE` | Calculates the distance between two strings—​that is, the number of insertions, deletions, or substitutions required to transform string1 into string2. If one or both of the strings are null the distance will be the largest integer value (2147483647). This function measures the distance in number of bytes and not in characters. As a consequence, strings stored using variable-width character sets (e.g., UTF-8) can cause counter-intuitive results. It is recommended to convert these strings to a fixed-width character set (AL16UTF16, for example) prior to passing them to this function. |
| `SEM_EDIT_DISTANCE_SIMILARITY` | Calculates the distance between string1 into string2 (as described in the `SEM_EDIT_DISTANCE` function), and returns the normalized value of the edit distance between two strings. The value is between 0 (no match) and 100 (perfect match). If one or both strings are null, the result will be 0. |
| `SEM_INSTR` | Finds the location of a substring within a specified string. |
| `SEM_JARO_WINKLER` | Calculates the measure of agreement between two strings using Jaro-Winkler method. The value is between 0 (no match) and 1 (perfect match). If one or both strings are null, the result will be 0. |
| `SEM_JARO_WINKLER_SIMILARITY` | Calculates the measure of agreement between two strings using Jaro-Winkler method, and returns a score between 0 (no match) and 100 (perfect match). If one or both strings are null, the result will be 0. |
| `SEM_NGRAMS_SIMILARITY` | Calculates the measure of agreement between two strings using the Dice coefficient similarity measure applied to the n-grams of the strings, and returns a score between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. The `ngrams_length` parameter defines the length of the n-grams (2 by default). |
| `SEM_NORMALIZE` | Returns a string with Latin (supplement, Extended-A, and Extended-B) characters converted into their ASCII equivalents, and other (space and non-alphanumeric) characters eliminated. |
| `SEM_NUMBER_TO_CHAR` | Converts a number to its standard string representation. |
| `SEM_SUBSTRING` | Returns a portion of string, beginning at character position, `substring_length` characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using characters as defined by the input character set. |
| `SEM_TIMESTAMP_TO_CHAR` | Converts a timestamp to its standard string representation. |
| `SEM_TO_CHAR` | Converts a string or a number to its standard string representation. |
| `SEM_TO_CHAR2` | Converts a value to its generic string representation. |
| `SEM_UUID_TO_CHAR` | Converts a UUID to its standard string representation. |
| `SEQ_NEXTVAL` | Get the next value of a sequence. This function is not supported in enrichers. |
| `SIGN` | Returns the sign of number. The sign is -1 if n<0, 0 if n=0, and 1 if n>0. |
| `SIN` | Returns the sine of number (an angle expressed in radians). |
| `SINH` | Returns the hyperbolic sine of number. |
| `SOUNDEX` | Returns a character string containing the phonetic representation of string. This function lets you compare words that are spelled differently, but sound alike in English. Phonetization methods such as `CAVERPHONE` or `METAPHONE` for person names and `METAPHONE` or `REFINEDSOUNDEX` for organization names give better results for matching. These methods are available in the Text Normalization and Transliteration plugins. |
| `SQRT` | Returns the square root of number. |
| `STANDARD_HASH` | Computes a hash value for a given expression and returns it in a RAW value. The optional method lets you choose the hash algorithm (defaults to SHA1) in the following list: SHA1, SHA256, SHA384, SHA512 and MD5. This function requires Oracle version 12c or above. |
| `SUBSTR` | Returns a portion of string, beginning at character position, `substring_length`-characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using characters as defined by the input character set. |
| `SUBSTR2` | Returns a portion of string, beginning at character position, `substring_length`-characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using UCS2 code points. |
| `SUBSTR4` | Returns a portion of string, beginning at character position, `substring_length`-characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using UCS4 code points. |
| `SUBSTRB` | Returns a portion of string, beginning at character position, `substring_length`-characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using bytes instead of characters. |
| `SUBSTRC` | Returns a portion of string, beginning at character position, `substring_length`-characters long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using Unicode complete characters. |
| `SYSDATE` | Returns the current date and time set for the operating system on which the database resides. |
| `SYSTIMESTAMP` | Returns the system date, including fractional seconds and timezone, of the system on which the database resides. |
| `SYS_CONTEXT` | Returns the value of parameter associated with the context namespace. |
| `SYS_EXTRACT_UTC` | Extracts the UTC (Coordinated Universal Time—​formerly Greenwich Mean Time) from a datetime value with timezone offset or timezone region name. |
| `SYS_GUID` | Generates and returns a globally unique identifier (RAW value) made up of 16 bytes. |
| `TAN` | Returns the tangent of number (an angle expressed in radians). |
| `TANH` | Returns the hyperbolic tangent of number. |
| `TO_BINARY_DOUBLE` | Returns a double-precision floating-point number. |
| `TO_BINARY_FLOAT` | Returns a single-precision floating-point number. |
| `TO_CHAR` | Converts expression to its string representation optionally using fmt and `nlsparam` for the conversion. |
| `TO_CLOB` | Converts expression to a CLOB (large string) |
| `TO_DATE` | Converts string to a date value. The `fmt` is a datetime model format specifying the format of string. If you omit `fmt`, then string must be in the default date format. If `fmt` is "J" for "Julian", then string must be an integer. |
| `TO_DSINTERVAL` | Converts a character string to an `INTERVAL DAY TO SECOND` value. |
| `TO_MULTI_BYTE` | Returns string with all of its single-byte characters converted to their corresponding multibyte characters. |
| `TO_NUMBER` | Converts expression to a number value using the optional format model fmt and `nlsparam`. |
| `TO_SINGLE_BYTE` | Returns string with all of its multibyte characters converted to their corresponding single-byte characters. |
| `TO_TIMESTAMP` | Converts string to timestamp value. The optional fmt specifies the format of string. |
| `TO_TIMESTAMP_TZ` | Converts string to a `TIMESTAMP WITH TIMEZONE` value. The optional fmt specifies the format of string. |
| `TO_YMINTERVAL` | Converts string to an `INTERVAL YEAR TO MONTH` type. |
| `TRANSLATE` | Returns expression with all occurrences of each character in `from_string` replaced by its corresponding character in `to_string`. Characters in expression that are not in `from_string` are not replaced. The argument `from_string` can contain more characters than `to_string`. In this case, the extra characters at the end of `from_string` have no corresponding characters in `to_string`. If these extra characters appear in string, then they are removed from the return value. |
| `TRIM` | Removes from the left and right ends of string all of the characters contained in `set_of_chars`. If you do not specify `set_of_chars`, it defaults to a single blank. |
| `TRUNC` | When expression is a date, returns expression with the time portion of the day truncated to the unit specified by the format model `fmt_or_number`. If you omit `fmt_or_number`, then date is truncated to the nearest day. When expression is a number, returns expression truncated to `fmt_or_number` decimal places. If `fmt_or_number` is omitted, then expression is truncated to 0 places. |
| `UNISTR` | Accepts a text literal or an expression that resolves to character data and returns it in the national character set. The database’s national character set can be either AL16UTF16 or UTF8. This function allows you to include Unicode string literals by specifying the Unicode encoding value of characters in the string. |
| `UPPER` | Returns a string with all letters uppercase. |
| `WIDTH_BUCKET` | Divides a specified range into equal-sized intervals, creating an equiwidth histogram. It returns the bucket number where the value of the evaluated expression falls. The expression must resolve to a numeric or datetime value. The `min_value` and `max_value` define the range’s endpoints and must also resolve to numeric or datetime values. These values cannot be null. |

## Functions for PostgreSQL

The following functions are available when using PostgreSQL.

| Function | Description |
|---|---|
| `ABS` | Returns the absolute value. |
| `ACOS` | Returns the inverse cosine. |
| `AGE` | Subtracts arguments, producing a symbolic result that uses years and months, rather than just days. |
| `ARRAY_AGG` | Concatenates input values—​including null values—​into an array. If the inputs are arrays, concatenates them into an array of one higher dimension (inputs must all have same dimensionality, and cannot be empty or null). |
| `ASCII` | Returns the ASCII code of the first character of the argument. For UTF-8, it returns the Unicode code point of the character. For other multibyte encodings, the argument must be an ASCII character. |
| `ASIN` | Returns the inverse sine. |
| `ATAN` | Returns the inverse tangent. |
| `ATAN2` | Returns the inverse tangent of `number_1/number_2`. |
| `AVG` | Returns the average (arithmetic mean) of all input values. |
| `BIT_AND` | Returns the bitwise AND of all non-null input values, or null if none. |
| `BIT_LENGTH` | Returns the number of bits in string. |
| `BIT_OR` | Returns the bitwise OR of all non-null input values, or null if none. |
| `BOOL_AND` | Returns true if all input values are true, otherwise false. |
| `BOOL_OR` | Returns true if at least one input value is true, otherwise false. |
| `BTRIM` | Removes the longest string consisting only of characters in characters (a space by default) from the start and end of string. |
| `CBRT` | Returns the cube root. |
| `CEIL` | Returns the nearest integer greater than or equal to argument. |
| `CEILING` | Returns the nearest integer greater than or equal to argument (same as `CEIL`). |
| `CHAR_LENGTH` | Returns the number of characters in string. |
| `CHR` | Returns the character with the given code. For UTF8 the argument is treated as a Unicode code point. For other multibyte encodings the argument must designate an ASCII character. The `NULL` (0) character is not allowed because text data types cannot store such bytes. |
| `CLOCK_TIMESTAMP` | Returns the current date and time (changes during statement execution). |
| `COALESCE` | Returns the first of its arguments that is not null. Null is returned only if all arguments are null. |
| `CONCAT` | Concatenates the text representations of all the arguments. Null arguments are ignored. |
| `CONCAT_WS` | Concatenates all but the first argument with separators. The first argument is used as the separator string. Null arguments are ignored. |
| `CONVERT` | Converts string to `dest_encoding`. The original encoding is specified by `src_encoding`. The string must be valid in this encoding. |
| `CONVERT_FROM` | Converts string to the database encoding. The original encoding is specified by `src_encoding`. The string must be valid in this encoding. |
| `CONVERT_TO` | Converts string to `dest_encoding`. |
| `COS` | Returns the cosine. |
| `COT` | Returns the cotangent. |
| `COUNT` | Returns the number of input rows for which the value of expression is not null. |
| `CURRENT_DATE` | Returns the current date. |
| `CURRENT_TIME` | Returns the current time of day. |
| `CURRENT_TIMESTAMP` | Returns the current date and time (at the beginning of current the transaction). |
| `CURRVAL` | Return value most recently obtained with `nextval` for specified sequence. |
| `DATERANGE` | Creates a range of dates. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `DATE_PART` | Gets subfield from a timestamp or an interval. The part to extract is defined by the text. |
| `DATE_TRUNC` | Truncates timestamp or interval to the precision specified in the text. |
| `DECODE` | Decodes binary data from textual representation in string. Options for format are same as for `ENCODE`. |
| `DEGREES` | Converts radians to degrees. |
| `DIFFERENCE` | Converts two strings to their Soundex codes and then reports the number of matching code positions. Since Soundex codes have four characters, the result ranges from zero to four, with zero being no match and four being an exact match. |
| `DIV` | Returns the integer quotient of `number_1/number_2`. |
| `DMETAPHONE` | Returns a character string containing the phonetic representation of string using the Double Metaphone algorithm. This function returns the primary code for the string. See also `DMETAPHONE_ALT`. |
| `DMETAPHONE_ALT` | Returns a character string containing the phonetic representation of string using the Double Metaphone algorithm. This function returns the secondary or alternate code for the string. See also `DMETAPHONE`. |
| `ENCODE` | Encodes binary data into a textual representation. Supported formats are: `base64`, `hex`, `escape`. `escape` converts zero bytes and high-bit-set bytes to octal sequences (\nnn) and doubles backslashes. |
| `EVERY` | Equivalent to `bool_and`. |
| `EXP` | Returns the exponential. |
| `FLOOR` | Returns the nearest integer less than or equal to argument. |
| `FORMAT` | Formats the arguments according to `format_string`. This function is similar to the C function `sprintf`. |
| `GET_BIT` | Extracts bit from string. |
| `GET_BYTE` | Extracts byte from string. |
| `GREATEST` | Selects the largest value from a list of any number of expressions. |
| `INITCAP` | Converts the first letter of each word to uppercase and the rest to lowercase. Words are sequences of alphanumeric characters separated by non-alphanumeric characters. |
| `INT4RANGE` | Creates a range of integers. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `INT8RANGE` | Creates a range of bigints. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `ISEMPTY` | Returns a boolean indicating whether the range is empty. |
| `ISFINITE` | Tests for finite date, interval or timestamp (not +/- infinity). |
| `JSONB_AGG` | Aggregates values as a JSON array. |
| `JSONB_OBJECT_AGG` | Aggregates name/value pairs as a JSON object. |
| `JSON_AGG` | Aggregates values as a JSON array. |
| `JSON_OBJECT_AGG` | Aggregates name/value pairs as a JSON object. |
| `JUSTIFY_DAYS` | Adjusts interval so 30-day periods are represented as months. |
| `JUSTIFY_HOURS` | Adjusts interval so 24-hour periods are represented as days. |
| `JUSTIFY_INTERVAL` | Adjusts interval using `justify_days` and `justify_hours`, with additional sign adjustments. |
| `LASTVAL` | Returns latest value obtained with `nextval` for any sequence. |
| `LEAST` | Selects the smallest value from a list of any number of expressions. |
| `LEFT` | Returns the first n characters in the string. When n is negative, return all but last n characters. |
| `LENGTH` | Returns the number of characters in string with an optional given encoding. The string must be valid in this encoding. |
| `LEVENSHTEIN` | Returns the Levenshtein distance between two strings, computed according to the cost specified for a character insertion, deletion, or substitution, respectively (you may set these values to 1). |
| `LEVENSHTEIN_LESS_EQUAL` | An accelerated version of the `LEVENSHTEIN` function that returns accurate values for actual distances smaller than `max_distance`. |
| `LN` | Returns the natural logarithm. |
| `LOCALTIME` | Returns the current time of day. |
| `LOCALTIMESTAMP` | Returns the current date and time (at start of current transaction). |
| `LOG` | Returns the logarithm in base 10. |
| `LOWER` | Converts string to lowercase. |
| `LOWER_INC` | Returns a boolean indicating whether the lower bound of the range is inclusive. |
| `LOWER_INF` | Returns a boolean indicating whether the lower bound of the range is infinite. |
| `LPAD` | Left-pads the string to the specified length by prepending `fill_text` (a space by default). If the string exceeds the specified length, it is truncated from the right. |
| `LTRIM` | Removes the longest string containing only characters from characters (a space by default) from the start of string. |
| `MAKE_DATE` | Creates date from integer year, month, and day fields. |
| `MAKE_INTERVAL` | Creates interval from years, months, weeks, days, hours, minutes, and seconds fields. If a field is left empty, it defaults to zero. |
| `MAKE_TIME` | Creates time from hour, minute, and seconds fields. |
| `MAKE_TIMESTAMP` | Creates timestamp from year, month, day, hour, minute, and seconds fields. |
| `MAKE_TIMESTAMPTZ` | Creates timestamp with timezone from year, month, day, hour, minute, and seconds fields; if timezone is not specified, the current timezone is used. |
| `MAX` | Returns the maximum value of expression across all input values. |
| `MD5` | Calculates the MD5 hash of string, returning the result in hexadecimal. |
| `METAPHONE` | Returns a character string containing the phonetic representation of string using the Metaphone algorithm, with a maximum length equal to the integer argument. |
| `MIN` | Returns the minimum value of expression across all input values. |
| `MOD` | Returns the remainder of `number_1/number_2`. |
| `NEXTVAL` | Increments the sequence and returns the next value. |
| `NOW` | Returns the current date and time (start of current transaction). |
| `NULLIF` | The `NULLIF` function returns a null value if `value1` equals `value2`; otherwise it returns `value1`. |
| `NUMRANGE` | Creates a range of numerics. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `NUM_NONNULLS` | Returns the number of non-null values. |
| `NUM_NULLS` | Returns the number of null values. |
| `OCTET_LENGTH` | Returns the number of bytes in string. |
| `OVERLAY` | Overlays string with `overlay_string`, starting at `start_position` and for length characters. |
| `PI` | Returns the pi constant. |
| `POWER` | Returns `number_1` raised to the power of `number_2` |
| `QUOTE_IDENT` | Returns the given string suitably quoted to be used as an identifier in an SQL statement string. Quotes are added only if necessary (i.e., if the string contains non-identifier characters or would be case-folded). Embedded quotes are properly doubled. |
| `QUOTE_LITERAL` | Returns the given string suitably quoted to be used as a string literal in an SQL statement string. Embedded single quotes and backslashes are properly doubled. `quote_literal` returns null on null input; if the argument might be null, `quote_nullable` is often more suitable. |
| `QUOTE_NULLABLE` | Returns the given string suitably quoted to be used as a string literal in an SQL statement string; or, if the argument is null, returns `NULL`. Embedded single quotes and backslashes are properly doubled. |
| `RADIANS` | Converts degrees to radians. |
| `RANDOM` | Returns a random value in the [0, 1] range. |
| `RANGE_LOWER` | Returns the lower bound of range. |
| `RANGE_MERGE` | Returns the smallest range which includes both of the given ranges. |
| `RANGE_UPPER` | Returns the upper bound of range. |
| `REGEXP_MATCH` | Returns the captured substring(s) resulting from the first match of a POSIX regular expression to the string. flags contain one or more of the following values: i - case-insensitive match, c - case-sensitive match. |
| `REGEXP_REPLACE` | Replaces the first substring matching a POSIX regular expression. flags contain one or more of the following values: i - case-insensitive match, c - Case-sensitive match. To replace all substrings, add 'g' to the flags. |
| `REGEXP_SPLIT_TO_ARRAY` | Splits the string using a POSIX regular expression as the delimiter. flags contain one or more of the following values: i - case-insensitive match, c - case-sensitive match. |
| `REPEAT` | Repeats string the specified number of times. |
| `REPLACE` | Replaces all occurrences in string of substring `from` with substring `to`. |
| `REVERSE` | Returns the reversed string. |
| `RIGHT` | Returns last n characters in the string. When n is negative, return all but first \|n\| characters. |
| `ROUND` | Rounds the number to the nearest integer or to int decimal places. |
| `RPAD` | Right-pads the string to the specified length by appending the characters fill (a space by default). If the string exceeds the specified length, it is truncated from the right. |
| `RTRIM` | Removes the longest string containing only characters from characters (a space by default) from the end of string. |
| `SCALE` | Returns the scale of the argument (the number of decimal digits in the fractional part). |
| `SEM_BOOLEAN_TO_CHAR` | Converts a boolean to its standard string representation. The returned value is `true` or `false`. |
| `SEM_CAST_BOOLEAN` | Explicitly casts its argument as a boolean. This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CAST_INTEGER` | Explicitly casts its argument as an integer. This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CAST_NUMERIC` | Explicitly casts its argument as a numeric value (decimal or integer). This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CAST_STRING` | Explicitly casts its argument as a string (varchar). This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CAST_TIMESTAMP` | Explicitly casts its argument as a timestamp. This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CAST_UUID` | Explicitly casts its argument as a UUID. This can help the database or JDBC driver to infer the type of a bound parameter. |
| `SEM_CONCAT` | Returns a string concatenating the input values with the separator. Set the `skip_null` parameter to '1' to skip null values. Set the `sep` parameter to an empty string '' to have no separator. |
| `SEM_EDIT_DISTANCE` | Calculates the number of insertions, deletions or substitutions required to transform string1 into string2. If one or both of the strings are null the distance will be the largest integer value (2147483647). |
| `SEM_EDIT_DISTANCE_SIMILARITY` | Calculates the number of insertions, deletions or substitutions required to transform string1 into string2, and returns the Normalized value of Edit Distance between two Strings. The value is between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. |
| `SEM_INSTR` | Finds the location of a substring within a specified string. |
| `SEM_NGRAMS_SIMILARITY` | Calculates the measure of agreement between two strings using the Dice coefficient similarity measure applied to the n-grams of the strings, and returns a score between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. The `ngrams_length` parameter defines the length of the n-grams (2 by default). |
| `SEM_NORMALIZE` | Returns a string with Latin (supplement, Extended-A, and Extended-B) characters converted into their ASCII equivalents, and other (space and non-alphanumeric) characters eliminated. |
| `SEM_NUMBER_TO_CHAR` | Converts a number to its standard string representation. |
| `SEM_SUBSTRING` | Returns a portion of string, beginning at character position, `substring_length`-character long. If position is 0, then it is treated as 1. If position is positive, then the function counts from the beginning of string to find the first character. If position is negative, then the function counts backward from the end of string. If `substring_length` is omitted, then the function returns all characters to the end of string. Length is calculated using characters as defined by the input character set. |
| `SEM_TIMESTAMP_TO_CHAR` | Converts a timestamp to its standard string representation. |
| `SEM_TO_CHAR` | Converts a string or a number to its standard string representation. |
| `SEM_TO_CHAR2` | Converts a value to its generic string representation. |
| `SEM_UUID_TO_CHAR` | Converts a UUID to its standard string representation. |
| `SEQ_NEXTVAL` | Gets the next value of a sequence. Note that this function is not supported in enrichers. |
| `SETSEED` | Sets the seed for subsequent random() calls (value between -1.0 and 1.0, inclusive). |
| `SETVAL` | Sets sequence’s current value. |
| `SET_BIT` | Sets bit in string. |
| `SET_BYTE` | Sets byte in string. |
| `SIGN` | Returns the sign of the argument (-1, 0, +1). |
| `SIN` | Returns the sine. |
| `SOUNDEX` | Returns a character string containing the phonetic representation of string. This function lets you compare words that are spelled differently, but sound alike in English. Phonetization methods such as `CAVERPHONE` or `METAPHONE` for person names and `METAPHONE` or `REFINEDSOUNDEX` for organization names give better results for matching. These methods are available in the Text Normalization and Transliteration plugins. |
| `SPLIT_PART` | Splits string on delimiter and return the element at position (counting from one). |
| `SQRT` | Returns the square root. |
| `STATEMENT_TIMESTAMP` | Returns the current date and time (start of current statement). |
| `STRING_AGG` | Returns input values concatenated into a string, separated by delimiter. |
| `STRPOS` | Returns the location of specified substring in string. |
| `SUBSTR` | Extracts a substring from string starting at from position and for count characters. |
| `SUBSTRING_REGEX_PATTERN` | Extracts from string a substring matching the pattern (a POSIX regular expression). |
| `SUBSTRING_SQL_PATTERN` | Extracts from string a substring matching an SQL regular expression. |
| `SUM` | Returns the sum of expression across all input values. |
| `TAN` | Returns the tangent. |
| `TIMEOFDAY` | Returns the current date and time (like `clock_timestamp`, but as a text string). |
| `TO_ASCII` | Converts string to ASCII from another encoding (only supports conversion from LATIN1, LATIN2, LATIN9, and WIN1250 encodings). |
| `TO_CHAR` | Convert the value (timestamp, interval, integer, real/double, numeric, string) to string according to the format. For more information about format patterns, see [https://www.postgresql.org/docs/current/functions-formatting.html](https://www.postgresql.org/docs/current/functions-formatting.html). |
| `TO_DATE` | Converts the string to date. for more information about format patterns, see [https://www.postgresql.org/docs/current/functions-formatting.html](https://www.postgresql.org/docs/current/functions-formatting.html). |
| `TO_HEX` | Converts number to its equivalent hexadecimal representation. |
| `TO_NUMBER` | Converts the string to numeric. For more information about format patterns, see [https://www.postgresql.org/docs/current/functions-formatting.html](https://www.postgresql.org/docs/current/functions-formatting.html). |
| `TO_TIMESTAMP` | Converts the string to timestamp. For more information about format patterns, see [https://www.postgresql.org/docs/current/functions-formatting.html](https://www.postgresql.org/docs/current/functions-formatting.html). |
| `TRANSACTION_TIMESTAMP` | Returns the current date and time (start of current transaction). |
| `TRANSLATE` | Replaces any character in string that matches a character in the `from` set with the corresponding character in the `to` set. If from is longer than `to`, occurrences of the extra characters in `from` are removed. |
| `TRUNC` | Truncates the number towards zero or to int decimal places. |
| `TSRANGE` | Creates a range of timestamps without timezone. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `TSTZRANGE` | Creates a range of timestamps with timezone. Inclusivity is a string with an opening/closing square bracket or parenthesis indicating inclusiveness, with a default of `(]`. |
| `UPPER` | Converts string to uppercase. |
| `UPPER_INC` | Returns a boolean indicating whether the upper bound of the range is inclusive. |
| `UPPER_INF` | Returns a boolean indicating whether the upper bound of the range is infinite. |
| `WIDTH_BUCKET` | Returns the bucket number to which operand would be assigned in a histogram having count equal-width buckets spanning the range b1 to b2; returns 0 or count+1 for an input outside the range. |
| `WIDTH_BUCKET_THRESHOLDS` | Returns the bucket number to which operand would be assigned given an array listing the lower bounds of the buckets; returns 0 for input less than the first lower bound; the thresholds array must be sorted, smallest first, or unexpected results will be obtained. |
| `XMLAGG` | Returns the concatenation of XML values. |

## Functions for Snowflake

| Function | Description |
|---|---|
| `ABS` | Returns the absolute value of a numeric expression. |
| `ACOS` | Computes the inverse cosine (arc cosine) of its input; the result is a number in the interval [0, pi]. |
| `ARRAY_AGG` | Returns the input values, pivoted into an array. |
| `ASCII` | Returns the ASCII code for the first character of a string. |
| `ASIN` | Computes the inverse sine (arc sine) of its argument; the result is a number in the interval [-pi/2, pi/2]. |
| `ATAN` | Computes the inverse tangent (arc tangent) of its argument; the result is a number in the interval [-pi, pi]. |
| `ATAN2` | Computes the inverse tangent (arc tangent) of the ratio of its two arguments. |
| `AVG` | Returns the average of non-null records. |
| `BASE64_DECODE_STRING` | Decodes a Base64-encoded string to a string. |
| `BIT_LENGTH` | Returns the length of a string or binary value in bits. |
| `BITAND` | Returns the bitwise `AND` of two numeric or binary expressions. |
| `BITAND_AGG` | Returns the bitwise `AND` value of all non-null numeric records in a group. |
| `BITOR` | Returns the bitwise `OR` of two numeric or binary expressions. |
| `BITOR_AGG` | Returns the bitwise `OR` value of all non-null numeric records in a group. |
| `BOOLAND` | Computes the boolean `AND` of two numeric expressions. |
| `BOOLAND_AGG` | Returns `true` if all non-null boolean records in a group evaluate to `true`. |
| `BOOLOR` | Computes the boolean `OR` of two numeric expressions. |
| `BOOLOR_AGG` | Returns `true` if at least one boolean record in a group evaluates to `true`. |
| `CBRT` | Returns the cubic root of a numeric expression. |
| `CEIL` | Returns values from the input expression rounded to the nearest equal or larger integer, or to the nearest equal or larger value with the specified number of places after the decimal point. |
| `CHR` | Converts a Unicode code point (including 7-bit ASCII) into the character that matches the input Unicode. |
| `COALESCE` | Returns the first non-null expression among its arguments, or `null` if all its arguments are null. |
| `CONCAT` | Concatenates one or more strings, or concatenates one or more binary values. |
| `CONCAT_WS` | Concatenates two or more strings, or concatenates two or more binary values. |
| `COS` | Computes the cosine of its argument; the argument should be expressed in radians. |
| `COT` | Computes the cotangent of its argument; the argument should be expressed in radians. |
| `COUNT` | Returns either the number of non-null records for the specified columns, or the total number of records. |
| `CURRENT_DATE` | Returns the current date of the system. |
| `CURRENT_TIME` | Returns the current time for the system. |
| `CURRENT_TIMESTAMP` | Returns the current timestamp for the system in the local time zone. |
| `DATE_PART` | Extracts the specified date or time part from a date, time, or timestamp. |
| `DATE_TRUNC` | Truncates a date, time, or timestamp value to the specified precision. |
| `DATEDIFF` | Calculates the difference between two date, time, or timestamp expressions based on the date or time part requested. |
| `DEGREES` | Converts radians to degrees. |
| `DIV0` | Performs division like the division operator (/), but returns `0` when the divisor is 0 (rather than reporting an error). |
| `EDITDISTANCE` | Computes the Levenshtein distance between two input strings. |
| `EXP` | Computes Euler number e raised to a floating-point value. |
| `FLOOR` | Returns values from the input expression rounded to the nearest equal or smaller integer, or to the nearest equal or smaller value with the specified number of places after the decimal point. |
| `GETBIT` | Given an integer value, returns the value of a bit at a specified position. |
| `GREATEST` | Returns the largest value from a list of expressions. |
| `HEX_DECODE_STRING` | Decodes a Hex-encoded string to a string. |
| `HEX_ENCODE` | Encodes the input using hexadecimal (also Hex or Base16) encoding. |
| `INITCAP` | Returns the input string with the first letter of each word in uppercase and the subsequent letters in lowercase. |
| `LEAST` | Returns the smallest value from a list of expressions. |
| `LEFT` | Returns the leftmost substring of its input. |
| `LENGTH` | Returns the length of an input string or binary value. |
| `LISTAGG` | Returns the concatenated input values, separated by the delimiter string. |
| `LN` | Returns the natural logarithm of a numeric expression. |
| `LOCALTIME` | Returns the current time for the system. |
| `LOCALTIMESTAMP` | Returns the current timestamp for the system in the local time zone. |
| `LOG` | Returns the logarithm of a numeric expression. |
| `LOWER` | Returns the input string with all characters converted to lowercase. |
| `LPAD` | Left-pads a string with characters from another string, or left-pads a binary value with bytes from another binary value. |
| `LTRIM` | Removes leading characters, including whitespace, from a string. |
| `MAX` | Returns the maximum value for the records within the expression. |
| `MD5` | Returns a 32-character Hex-encoded string containing the 128-bit MD5 message digest. |
| `MIN` | Returns the minimum value for the records within the expression. |
| `MOD` | Returns the remainder of input expression1 divided by input expression2. |
| `NULLIF` | Returns `null` if expression1 is equal to expression2, otherwise returns expression1. |
| `OBJECT_AGG` | Returns one object per group. |
| `OCTET_LENGTH` | Returns the length of a string or binary value in bytes. |
| `PI` | Returns the value of pi as a floating-point value. |
| `POSITION` | Searches for the first occurrence of the first argument in the second argument and, if successful, returns the position (1-based) of the first argument in the second argument. |
| `POWER` | Returns a number (x) raised to the specified power (y). |
| `RADIANS` | Converts degrees to radians. |
| `RANDOM` | Each call returns a pseudo-random 64-bit integer. |
| `REGEXP_REPLACE` | Returns the subject with the specified pattern (or all occurrences of the pattern) either removed or replaced by a replacement string. |
| `REGEXP_SUBSTR` | Returns the substring that matches a regular expression within a string. |
| `REPEAT` | Builds a string by repeating the input for the specified number of times. |
| `REPLACE` | Removes all occurrences of a specified substring, and optionally replaces them with another substring. |
| `REVERSE` | Reverses the order of characters in a string, or of bytes in a binary value. |
| `RIGHT` | Returns a rightmost substring of its input. |
| `ROUND` | Returns rounded values for the input expression. |
| `RPAD` | Right-pads a string with characters from another string, or right-pads a binary value with bytes from another binary value. |
| `RTRIM` | Removes trailing characters, including whitespace, from a string. |
| `SIGN` | Returns the sign of its argument. |
| `SIN` | Computes the sine of its argument; the argument should be expressed in radians. |
| `SOUNDEX` | Returns a string that contains a phonetic representation of the input string. |
| `SQRT` | Returns the square-root of a non-negative numeric expression. |
| `SUBSTR` | Returns the portion of the string or binary value from `base_expr`, starting from the character/byte specified by `start_expr`, with optionally limited length. |
| `SUM` | Returns the sum of non-null records for the expression. |
| `TAN` | Computes the tangent of its argument; the argument should be expressed in radians. |
| `TO_DATE` | Converts an input expression to a date. |
| `TO_NUMBER` | Converts an input expression to a fixed-point number. |
| `TO_TIMESTAMP` | Converts an input expression into the corresponding timestamp. |
| `TRANSLATE` | Replaces characters in an expression. |
| `TRIM` | Removes leading and trailing characters from a string. |
| `TRUNC` | Truncates a date, time, or timestamp value to the specified precision. |
| `UPPER` | Returns the input string expression with all characters converted to uppercase. |
| `WIDTH_BUCKET` | Constructs equi-width histograms, in which the histogram range is divided into intervals of identical size, and returns the bucket number into which the value of an expression falls, after it has been evaluated. |
| `SEM_CONCAT` | Returns a string concatenating the input values with the separator. Set the `skip_null` parameter to `''1''` to skip null values. Set the `sep` parameter to an empty string (`''''`) to have no separator. |
| `SEQ_NEXTVAL` | Get the next value of a sequence. Not supported in enrichers. |
| `SEM_NORMALIZE` | Returns a string with Latin (supplement, Extended-A, and Extended-B) characters converted into their ASCII equivalents, and other (space and non-alphanumeric) characters eliminated. |
| `SEM_CAST_BOOLEAN` | Explicitly cast its argument as a boolean. This can help the database or JDBC driver infer the type of a bound parameter. |
| `SEM_CAST_DATE` | Explicitly cast its argument as a date. |
| `SEM_CAST_INTEGER` | Explicitly cast its argument as an integer value. This can help the database or JDBC driver infer the type of a bound parameter. |
| `SEM_CAST_NUMERIC` | Explicitly cast its argument as a numeric value (decimal or integer). This can help the database or JDBC driver infer the type of a bound parameter. |
| `SEM_CAST_STRING` | Explicitly cast its argument as a string (VARCHAR). This can help the database or JDBC driver infer the type of a bound parameter. |
| `SEM_CAST_TIMESTAMP` | Explicitly cast its argument as a timestamp. This can help the database or JDBC driver infer the type of a bound parameter. |
| `SEM_TO_CHAR` | Converts a string or a number to its standard string representation. |
| `SEM_TO_CHAR2` | Generic conversion to a string representation. |
| `SEM_DATE_TO_CHAR` | Converts a date to its standard string representation. |
| `SEM_TIMESTAMP_TO_CHAR` | Converts a timestamp to its standard string representation. |
| `SEM_NUMBER_TO_CHAR` | Converts a number to its standard string representation. |
| `SEM_BOOLEAN_TO_CHAR` | Converts a boolean to its standard string representation (`true` or `false`). |
| `SEM_INSTR` | Finds the location of a substring within a specified string. |
| `SEM_EDIT_DISTANCE` | Calculates the number of insertions, deletions or substitutions required to transform expression1 into expression2. If one or both of the strings are null the distance will be the largest integer value (2147483647). |
| `SEM_JARO_WINKLER_SIMILARITY` | Calculates the measure of agreement between two strings using Jaro-Winkler method, and returns a score between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. |
| `SEM_EDIT_DISTANCE_SIMILARITY` | Calculates the number of insertions, deletions or substitutions required to transform expression1 into expression2, and returns the normalized value of the edit distance between two strings. The value is between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. |

## Functions for SQL Server

The following functions are available when using SQL Server.

| Function | Description |
|---|---|
| `ABS` | Returns the absolute (positive) value of the specified numeric expression. |
| `ACOS` | Returns the angle, in radians, whose cosine is the specified float expression. |
| `APPROX_COUNT_DISTINCT` | Returns the approximate number of unique non-null values in a group. |
| `ASCII` | Returns the ASCII code value of the leftmost character of a character expression. |
| `ASIN` | Returns the angle, in radians, whose sine is the specified float expression. |
| `ATAN` | Returns the angle, in radians, whose tangent is a specified expression. |
| `ATNS` | Returns the angle—​in radians—​between the positive x-axis and the ray from the origin to the point (y, x), where x and y are the values of the two specified float expressions. |
| `AVG` | Returns the average of the values in a group. It ignores null values. |
| `CEILING` | Returns the smallest integer greater than, or equal to, the specified numeric expression. |
| `CHARINDEX` | Searches for one character expression inside a second character expression, returning the starting position of the first expression if found. |
| `CHECKSUM_AGG` | Returns the checksum of the values in a group. |
| `CHOOSE` | Returns the item at the specified index from a list of values in SQL Server. |
| `COALESCE` | Evaluates the arguments in order and returns the current value of the first expression that initially does not evaluate to `NULL`. |
| `CONCAT` | Concatenates two or more strings together. |
| `COS` | Returns the trigonometric cosine of the specified angle—​measured in radians—​in the specified expression. |
| `COT` | Returns the trigonometric cotangent of the specified angle—​in radians—​in the specified float expression. |
| `COUNT` | Returns the number of input rows for which the value of the expression is not null. |
| `DATEADD` | Adds a specified number value (as a signed integer) to a specified datepart of an input date value, and then returns that modified value. Datepart must be one of the following values, provided between quotes (e.g., 'year'): year, quarter, month, dayofyear, day, week, weekday, hour, minute, second, millisecond, microsecond, nanosecond. |
| `DATEDIFF` | Returns the count (as a signed integer value) of the specified datepart boundaries crossed between the specified startdate and enddate. Datepart must be one of the following values, provided between quotes (e.g., 'year'): year, quarter, month, dayofyear, day, week, weekday, hour, minute, second, millisecond, microsecond, nanosecond. |
| `DATEFROMPARTS` | Returns a date value that maps to the specified year, month, and day values. |
| `DATENAME` | Returns a character string representing the specified datepart of the specified date. Note that datepart must be one of the following values, provided between quotes (e.g., 'year'): year, quarter, month, dayofyear, day, week, weekday, hour, minute, second, millisecond, microsecond, nanosecond. |
| `DATEPART` | Returns an integer representing the specified datepart of the specified date. Note that datepart must be one of the following values, provided between quotes (e.g., 'year'): year, quarter, month, dayofyear, day, week, weekday, hour, minute, second, millisecond, microsecond, nanosecond. |
| `DATETIME2FROMPARTS` | Returns a datetime2 value for the specified date and time arguments. The returned value has a precision specified by the precision argument. |
| `DAY` | Returns an integer that represents the day (day of the month) of the specified date. |
| `DEGREES` | Returns the corresponding angle, in degrees, for an angle specified in radians. |
| `DIFFERENCE` | Returns an integer value measuring the difference between the `SOUNDEX` values of two different character expressions. |
| `EOMONTH` | Returns the last day of the month containing a specified date, with an optional offset. |
| `EXP` | Returns the exponential value of the specified float expression. |
| `FLOOR` | Returns the largest integer less than or equal to the specified numeric expression. |
| `FORMAT` | Returns a value formatted with the specified format and optional culture in SQL Server 2017. Use the `FORMAT` function for locale-aware formatting of date/time and number values as strings. For general data type conversions, use `CAST` or `CONVERT`. |
| `GETDATE` | Returns the current database system timestamp as a datetime value without the database timezone offset. This value is derived from the operating system of the computer on which the instance of SQL Server is running. |
| `HASHBYTES` | Returns the MD2, MD4, MD5, SHA, SHA1, or SHA2 hash of its input in SQL Server. |
| `ISDATE` | Returns 1 if the expression is a valid date, time, or datetime value; otherwise, 0. |
| `ISNULL` | Replaces NULL with the specified replacement value. |
| `LEFT` | Returns the left part of a character string with the specified number of characters. |
| `LEN` | Returns the number of characters of the specified string expression, excluding trailing blanks. |
| `LENGTH` | Returns the length of string. Length is calculated using characters as defined by the input character set. |
| `LOG` | Returns the natural logarithm of the specified float expression. |
| `LOG10` | Returns the base-10 logarithm of the specified float expression. |
| `LOWER` | Returns a character expression after converting uppercase character data to lowercase. |
| `LPAD` | Returns the string, left-padded to length number characters with the sequence of characters in expression2. If you do not specify expression2, then the default is a single blank. |
| `LTRIM` | Returns a character expression after it removes leading blanks. |
| `MAX` | Returns the maximum value in the expression. |
| `MIN` | Returns the minimum value in the expression. |
| `MONTH` | Returns an integer that represents the month of the specified date. |
| `NCHAR` | Returns the Unicode character with the specified integer code, as defined by the Unicode standard. |
| `NEWID` | Creates a unique value of type `uniqueidentifier`. |
| `NULLIF` | Returns a null value if the two specified expressions are equal. |
| `PATINDEX` | Returns the starting position of the first occurrence of a pattern in a specified expression, or zeros if the pattern is not found, on all valid text and character data types. |
| `PI` | Returns the constant value of pi. |
| `POWER` | Returns the value of the specified expression to the specified power. |
| `QUOTENAME` | Returns a Unicode string with the delimiters added to make the input string a valid SQL Server delimited identifier. |
| `RADIAN` | Returns radians when a numeric expression, in degrees, is entered. |
| `RAND` | Returns a pseudo-random float value from 0 through 1, exclusive. |
| `REPLACE` | Replaces all occurrences of a specified string value with another string value. |
| `REPLICATE` | Repeats a string value a specified number of times. |
| `REVERSE` | Returns the reverse order of a string value. |
| `RIGHT` | Returns the right part of a character string with the specified number of characters. |
| `ROUND` | Returns a numeric value, rounded to the specified length or precision. |
| `RTRIM` | Returns a character string after truncating all trailing spaces. |
| `SEM_BOOLEAN_TO_CHAR` | Converts a boolean to its standard string representation. The returned value is `true` or `false`. |
| `SEM_CAST_NUMERIC` | Explicitly casts its argument as an integer value. This can help the database or JDBC driver to infer the type of a bound parameter. If the value provided is a valid number, rounds to the nearest integer; otherwise, returns `NULL`. |
| `SEM_CONCAT` | Returns a string concatenating the input values with the separator. Set the `skip_null` parameter to '1' to skip null values. Set the `sep` parameter to an empty string '' to have no separator. |
| `SEM_DATE_TO_CHAR` | Converts a timestamp to its standard string representation. |
| `SEM_EDIT_DISTANCE` | Calculates the number of insertions, deletions or substitutions required to transform string1 into string2. If one or both of the strings are null, the distance will be the largest integer value (2147483647). |
| `SEM_EDIT_DISTANCE_SIMILARITY` | Calculates the number of insertions, deletions or substitutions required to transform string1 into string2, and returns the normalized value of Edit Distance between two Strings. The value is between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. |
| `SEM_INSTR` | Finds the location of a substring within a specified string. |
| `SEM_NGRAMS_SIMILARITY` | Calculates the measure of agreement between two strings using the Dice coefficient similarity measure applied to the n-grams of the strings, and returns a score between 0 (no match) and 100 (perfect match). If one or both strings are null the result will be 0. The `ngrams_length` parameter defines the length of the n-grams (2 by default). |
| `SEM_NORMALIZE` | Returns a string with Latin (supplement, Extended-A, and Extended-B) characters converted into their ASCII equivalents, and other (space and non-alphanumeric) characters eliminated. |
| `SEM_NUMBER_TO_CHAR` | Converts a number to its standard string representation. |
| `SEM_SUBSTRING` | Returns part of a character, binary, text, or image expression. |
| `SEM_TIMESTAMP_TO_CHAR` | Converts a timestamp to its standard string representation. |
| `SEM_TO_CHAR` | Converts a string or a number to its standard string representation. |
| `SEM_TO_CHAR2` | Converts a value to its generic string representation. |
| `SEM_UUID_TO_CHAR` | Converts a UUID to its standard string representation. |
| `SEQ_NEXTVAL` | Gets the next value of a sequence. Note that this function is not supported in enrichers. |
| `SIGN` | Returns the positive (+1), zero (0), or negative (-1) sign of the specified expression. |
| `SIN` | Returns the trigonometric sine of the specified angle, in radians, and in an approximate numeric, float, expression. |
| `SOUNDEX` | Returns a four-character (SOUNDEX) code to evaluate the similarity of two strings. |
| `SPACE` | Returns a string of repeated spaces. |
| `SQRT` | Returns the square root of the specified float value. |
| `SQUARE` | Returns the square of the specified float value. |
| `STDEV` | Returns the statistical standard deviation of all values in the specified expression. |
| `STDEVP` | Returns the statistical standard deviation for the population for all values in the specified expression. |
| `STR` | Returns character data converted from numeric data. |
| `STRING_AGG` | Concatenates the values of string expressions and places separator values between them. The separator is not added at the end of string. |
| `STRING_ESCAPE` | Escapes special characters in texts and returns text with escaped characters. `STRING_ESCAPE` is a deterministic function. |
| `STRING_SPLIT` | Splits the character expression using specified separator. |
| `STUFF` | Inserts a string into another string. Thsi function deletes a specified length of characters in the first string at the start position and then inserts the second string into the first string at the start position. |
| `SUBSTRING` | Returns part of a character, binary, text, or image expression in SQL Server. |
| `SUM` | Returns the sum of all the values, or only the `DISTINCT` values, in the expression. |
| `SYSDATETIME` | Returns a `datetime2(7)` value that contains the date and time of the computer on which the instance of SQL Server is running. |
| `TAN` | Returns the tangent of the input expression. |
| `TRANSLATE` | Returns the string provided as a first argument after some characters specified in the second argument are translated into a destination set of characters. |
| `TRIM` | Removes the characters (a space by default) from the start or end of the string expression. |
| `UNICODE` | Returns the integer value, as defined by the Unicode standard, for the first character of the input expression. |
| `UPPER` | Returns a character expression with lowercase character data converted to uppercase. |
| `VAR` | Returns the statistical variance of all values in the specified expression. |
| `VARP` | Returns the statistical variance for the population for all values in the specified expression. |
| `YEAR` | Returns an integer that represents the year of the specified date. |
