# Mag Hawk V2025 DAT File Structure

This document describes the binary structure of Mag Hawk V2025 `.dat` files.
It intentionally focuses only on the file format, not on KLuxMap UI behavior or
post-processing output.

## File Name

V2025 files use this naming convention:

```text
Mag_YYMMDD_HHMM.dat
```

Example:

```text
Mag_260612_0101.dat
```

The timestamp in the name identifies the file, but each full data block also
contains its own date and time fields.

## Endianness

All numeric fields are little-endian.

```text
<
```

## Top-Level File Layout

A V2025 `.dat` file may be stored in either of these forms:

```text
compressed MLZO container
raw uncompressed data stream
```

If the first 4 bytes are `MLZO`, the file is a compressed container. Otherwise,
the file content is treated as the raw data stream directly.

## MLZO Container

Compressed files begin with this header:

```text
offset  size  type       description
0       4     bytes      magic, ASCII "MLZO"
4       4     uint32 LE  expected decompressed raw data size
8       ...   blocks     payload blocks
```

After the 8-byte file header, payload blocks repeat until the end of file.

```text
offset  size  type       description
0       1     uint8      compression flag
1       1     uint8      checksum
2       2     uint16 LE  payload size in bytes
4       N     bytes      payload
4+N     0..3  padding    zero to three bytes for 4-byte alignment
```

The compression flag has this meaning:

```text
0       payload is uncompressed raw data
nonzero payload is minilzo-compressed data
```

The checksum is the lower 8 bits of the payload byte sum:

```text
checksum = sum(payload) & 0xFF
```

The payload size does not include padding bytes. The next payload block starts
after padding to the next 4-byte boundary.

## Raw Data Stream

After decompression, or when the file is already raw, the data stream consists
of variable-length records:

```text
Full Block
Short Block
```

The first record is expected to be a full block. After that, a record is treated
as a short block when the next 2 bytes equal `0xAAAA`; otherwise it is parsed as
a full block.

## Full Block

A full block contains complete time, position, altitude, and ADC data.

Struct format:

```python
"<6BHddh6x4i"
```

Total size:

```text
48 bytes
```

Layout:

```text
offset  size  type       field
0       1     uint8      month
1       1     uint8      day
2       1     uint8      year, two digits
3       1     uint8      hours
4       1     uint8      minutes
5       1     uint8      seconds
6       2     uint16 LE  subseconds, milliseconds
8       8     double LE  latitude, decimal degrees
16      8     double LE  longitude, decimal degrees
24      2     int16 LE   altitude
26      6     padding    unused padding bytes
32      4     int32 LE   ADC0
36      4     int32 LE   ADC1
40      4     int32 LE   ADC2
44      4     int32 LE   ADC3
```

The full block updates the current stream context:

```text
year
month
day
hours
minutes
seconds
latitude
longitude
altitude
```

Short blocks that follow use this context for fields that they do not store.

## Short Block

A short block stores only a short-block marker, milliseconds, and ADC data.
It reuses the date, second-level time, position, and altitude from the previous
full block.

Header value:

```text
0xAAAA
```

Struct format:

```python
"<HH4i"
```

Total size:

```text
20 bytes
```

Layout:

```text
offset  size  type       field
0       2     uint16 LE  header, 0xAAAA
2       2     uint16 LE  subseconds, milliseconds
4       4     int32 LE   ADC0
8       4     int32 LE   ADC1
12      4     int32 LE   ADC2
16      4     int32 LE   ADC3
```

The short block does not contain these fields:

```text
year
month
day
hours
minutes
seconds
latitude
longitude
altitude
```

Those values are inherited from the most recent full block.

## ADC Channels

The V2025 record stores four signed 32-bit ADC values.

```text
ADC0
ADC1
ADC2
ADC3
```

For the current Mag Hawk V2025 sensor mapping:

```text
ADC0 = X axis
ADC1 = Y axis
ADC2 = Z axis
ADC3 = unused
```

The values in the file are raw integer ADC counts.

## Field Summary

```text
month       1..12
day         1..31
year        two-digit year, e.g. 26 means 2026
hours       0..23
minutes     0..59
seconds     0..59
subseconds  milliseconds
latitude    decimal degrees
longitude   decimal degrees
altitude    signed integer altitude value
ADC0..ADC3  signed 32-bit raw ADC counts
```
