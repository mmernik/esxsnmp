# ESxSNMP #

ESxSNMP is a system for collecting and storing large sets of SNMP data.  ESxSNMP uses a hybrid model for storing data using [TSDB](http://code.google.com/p/tsdb/) for time series data and an SQL database for everything else.  All data is available via a REST style interface (as JSON) allowing for easy integration with other tools.  ESxSNMP provides linkage to [perfSONAR](http://www.perfsonar.net) and to the [Graphite](http://graphite.wikidot.com/) graphing package.

Time series data such as interface counters is stored using [TSDB](http://code.google.com/p/tsdb/).  TSDB is a library for storing time series data with no loss of information.  TSDB optimizes the store of it's data so that data which share similar timestamps is stored nearby on the disk allowing very fast access to specific time ranges. Data such as interface description and interface type are stored in an SQL database.  Storing this data in an SQL database allows us to use the full expressiveness of SQL to query this data.  Since this data changes relatively infrequently the demands placed on the SQL server are fairly modest.

ESxSNMP was designed with the needs of the ESnet network engineering team in mind, but should be useful in many situations.

You can find additional information on the [talks](Talks.md) page.