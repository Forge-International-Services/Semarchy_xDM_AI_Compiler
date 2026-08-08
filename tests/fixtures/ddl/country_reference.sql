-- Single source: the finance team's reference schema. ~249 rows, static.
CREATE TABLE COUNTRY (
    CODE  VARCHAR(2)  NOT NULL PRIMARY KEY,
    NAME  VARCHAR(80) NOT NULL
);
