use crate::{
    COMPILED_PACK_BYTES_LIMIT, DECODED_ASSET_BYTES_LIMIT, DECODED_ASSETS_TOTAL_BYTES_LIMIT,
    NESTING_LIMIT, SEMANTIC_ASSET_LIMIT, STRING_BYTES_LIMIT, TOKEN_LIMIT, ThemeError, reject,
};
use serde_json::Value;
use std::collections::HashSet;

pub(crate) fn decode_canonical_value(bytes: &[u8]) -> Result<Value, ThemeError> {
    if bytes.len() > COMPILED_PACK_BYTES_LIMIT {
        return reject("E_LIMIT_PACK", "compiled package exceeds 256 KiB");
    }
    if std::str::from_utf8(bytes).is_err() {
        return reject("E_UTF8", "package is not valid UTF-8");
    }
    let Some(body) = bytes.strip_suffix(b"\n") else {
        return reject(
            "E_JSON_NONCANONICAL",
            "canonical JSON requires one final newline",
        );
    };
    Preflight::new(body).run()?;
    let value: Value = serde_json::from_slice(body).map_err(|_| ThemeError {
        code: "E_JSON_MALFORMED",
        message: "malformed JSON",
    })?;
    let mut expected = canonical_json_bytes(&value)?;
    expected.push(b'\n');
    if expected != bytes {
        return reject("E_JSON_NONCANONICAL", "JSON bytes are not canonical");
    }
    Ok(value)
}

pub(crate) fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, ThemeError> {
    let mut output = Vec::new();
    write_canonical(value, &mut output)?;
    Ok(output)
}

fn write_canonical(value: &Value, output: &mut Vec<u8>) -> Result<(), ThemeError> {
    match value {
        Value::Null => output.extend_from_slice(b"null"),
        Value::Bool(true) => output.extend_from_slice(b"true"),
        Value::Bool(false) => output.extend_from_slice(b"false"),
        Value::String(string) => serde_json::to_writer(output, string).map_err(|_| ThemeError {
            code: "E_JSON_MALFORMED",
            message: "string encoding failed",
        })?,
        Value::Number(number) => {
            if let Some(integer) = number.as_i64() {
                output.extend_from_slice(integer.to_string().as_bytes());
            } else if let Some(integer) = number.as_u64() {
                output.extend_from_slice(integer.to_string().as_bytes());
            } else {
                let Some(float) = number.as_f64() else {
                    return reject("E_JSON_MALFORMED", "invalid JSON number");
                };
                if !float.is_finite() {
                    return reject("E_NUMBER_NONFINITE", "numbers must be finite");
                }
                if float == 0.0 {
                    output.push(b'0');
                } else if float.fract() == 0.0 {
                    output.extend_from_slice(format!("{float:.0}").as_bytes());
                } else {
                    output.extend_from_slice(number.to_string().as_bytes());
                }
            }
        }
        Value::Array(values) => {
            output.push(b'[');
            for (index, child) in values.iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                write_canonical(child, output)?;
            }
            output.push(b']');
        }
        Value::Object(values) => {
            output.push(b'{');
            let mut entries: Vec<_> = values.iter().collect();
            entries.sort_unstable_by(|(left, _), (right, _)| left.cmp(right));
            for (index, (key, child)) in entries.into_iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                serde_json::to_writer(&mut *output, key).map_err(|_| ThemeError {
                    code: "E_JSON_MALFORMED",
                    message: "object key encoding failed",
                })?;
                output.push(b':');
                write_canonical(child, output)?;
            }
            output.push(b'}');
        }
    }
    Ok(())
}

struct Preflight<'a> {
    input: &'a [u8],
    position: usize,
    token_count: usize,
    decoded_assets_total: f64,
}

impl<'a> Preflight<'a> {
    fn new(input: &'a [u8]) -> Self {
        Self {
            input,
            position: 0,
            token_count: 0,
            decoded_assets_total: 0.0,
        }
    }

    fn run(mut self) -> Result<(), ThemeError> {
        self.skip_whitespace();
        self.value(0, &mut Vec::new())?;
        self.skip_whitespace();
        if self.position != self.input.len() {
            return reject("E_JSON_MALFORMED", "trailing data after JSON value");
        }
        Ok(())
    }

    fn value(&mut self, depth: usize, path: &mut Vec<String>) -> Result<(), ThemeError> {
        if depth > NESTING_LIMIT {
            return reject("E_LIMIT_NESTING", "JSON nesting exceeds 32");
        }
        self.skip_whitespace();
        match self.peek() {
            Some(b'{') => self.object(depth, path),
            Some(b'[') => self.array(depth, path),
            Some(b'\"') => self.string().map(|_| ()),
            Some(b't') => self.literal(b"true"),
            Some(b'f') => self.literal(b"false"),
            Some(b'n') => self.literal(b"null"),
            Some(b'N') | Some(b'I') => reject("E_NUMBER_NONFINITE", "numbers must be finite"),
            Some(b'-') if self.input.get(self.position + 1) == Some(&b'I') => {
                reject("E_NUMBER_NONFINITE", "numbers must be finite")
            }
            Some(b'-' | b'0'..=b'9') => {
                let number = self.number()?;
                if is_decoded_bytes(path) {
                    if number > DECODED_ASSET_BYTES_LIMIT as f64 {
                        return reject("E_LIMIT_ASSET_BYTES", "decoded asset exceeds 512 KiB");
                    }
                    self.decoded_assets_total += number;
                    if self.decoded_assets_total > DECODED_ASSETS_TOTAL_BYTES_LIMIT as f64 {
                        return reject("E_LIMIT_ASSETS_TOTAL", "decoded asset total exceeds 4 MiB");
                    }
                }
                Ok(())
            }
            _ => reject("E_JSON_MALFORMED", "malformed JSON value"),
        }
    }

    fn object(&mut self, depth: usize, path: &mut Vec<String>) -> Result<(), ThemeError> {
        self.position += 1;
        self.skip_whitespace();
        if self.consume(b'}') {
            return Ok(());
        }
        let mut keys = HashSet::new();
        let mut entries = 0usize;
        loop {
            self.skip_whitespace();
            if self.peek() != Some(b'\"') {
                return reject("E_JSON_MALFORMED", "object key must be a string");
            }
            let key = self.string()?;
            if !keys.insert(key.clone()) {
                return reject("E_JSON_DUPLICATE", "duplicate object key");
            }
            entries += 1;
            if is_token_layer(path) {
                self.token_count += 1;
                if self.token_count > TOKEN_LIMIT {
                    return reject("E_LIMIT_TOKENS", "token count exceeds 1024");
                }
            }
            if is_asset_items(path) && entries > SEMANTIC_ASSET_LIMIT {
                return reject("E_LIMIT_ASSETS", "semantic asset count exceeds 64");
            }
            self.skip_whitespace();
            if !self.consume(b':') {
                return reject("E_JSON_MALFORMED", "missing object separator");
            }
            path.push(key);
            self.value(depth + 1, path)?;
            path.pop();
            self.skip_whitespace();
            if self.consume(b'}') {
                return Ok(());
            }
            if !self.consume(b',') {
                return reject("E_JSON_MALFORMED", "missing object delimiter");
            }
        }
    }

    fn array(&mut self, depth: usize, path: &mut Vec<String>) -> Result<(), ThemeError> {
        self.position += 1;
        self.skip_whitespace();
        if self.consume(b']') {
            return Ok(());
        }
        loop {
            self.value(depth + 1, path)?;
            self.skip_whitespace();
            if self.consume(b']') {
                return Ok(());
            }
            if !self.consume(b',') {
                return reject("E_JSON_MALFORMED", "missing array delimiter");
            }
        }
    }

    fn string(&mut self) -> Result<String, ThemeError> {
        let start = self.position;
        self.position += 1;
        let mut escaped = false;
        while let Some(byte) = self.peek() {
            self.position += 1;
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'\"' {
                bounded_string_bytes(&self.input[start + 1..self.position - 1])?;
                let string: String = serde_json::from_slice(&self.input[start..self.position])
                    .map_err(|_| ThemeError {
                        code: "E_JSON_MALFORMED",
                        message: "malformed JSON string",
                    })?;
                return Ok(string);
            } else if byte < 0x20 {
                return reject("E_JSON_MALFORMED", "unescaped control character in string");
            }
        }
        reject("E_JSON_MALFORMED", "unterminated JSON string")
    }

    fn number(&mut self) -> Result<f64, ThemeError> {
        let start = self.position;
        while matches!(
            self.peek(),
            Some(b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9')
        ) {
            self.position += 1;
        }
        if std::str::from_utf8(&self.input[start..self.position])
            .ok()
            .and_then(|number| number.parse::<f64>().ok())
            .is_some_and(|number| !number.is_finite())
        {
            return reject("E_NUMBER_NONFINITE", "numbers must be finite");
        }
        serde_json::from_slice::<Value>(&self.input[start..self.position])
            .ok()
            .and_then(|value| value.as_f64())
            .ok_or(ThemeError {
                code: "E_JSON_MALFORMED",
                message: "malformed JSON number",
            })
    }

    fn literal(&mut self, literal: &[u8]) -> Result<(), ThemeError> {
        if self.input.get(self.position..self.position + literal.len()) == Some(literal) {
            self.position += literal.len();
            Ok(())
        } else {
            reject("E_JSON_MALFORMED", "malformed JSON literal")
        }
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\r' | b'\n')) {
            self.position += 1;
        }
    }

    fn consume(&mut self, expected: u8) -> bool {
        if self.peek() == Some(expected) {
            self.position += 1;
            true
        } else {
            false
        }
    }

    fn peek(&self) -> Option<u8> {
        self.input.get(self.position).copied()
    }
}

fn bounded_string_bytes(encoded: &[u8]) -> Result<(), ThemeError> {
    let mut position = 0usize;
    let mut decoded_bytes = 0usize;
    while position < encoded.len() {
        if encoded[position] != b'\\' {
            decoded_bytes += 1;
            position += 1;
        } else {
            let Some(escape) = encoded.get(position + 1).copied() else {
                return reject("E_JSON_MALFORMED", "malformed JSON string escape");
            };
            match escape {
                b'\"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => {
                    decoded_bytes += 1;
                    position += 2;
                }
                b'u' => {
                    let high = hex_quad(encoded.get(position + 2..position + 6))?;
                    if (0xd800..=0xdbff).contains(&high) {
                        if encoded.get(position + 6..position + 8) != Some(b"\\u") {
                            return reject("E_JSON_MALFORMED", "unpaired Unicode surrogate");
                        }
                        let low = hex_quad(encoded.get(position + 8..position + 12))?;
                        if !(0xdc00..=0xdfff).contains(&low) {
                            return reject("E_JSON_MALFORMED", "unpaired Unicode surrogate");
                        }
                        decoded_bytes += 4;
                        position += 12;
                    } else if (0xdc00..=0xdfff).contains(&high) {
                        return reject("E_JSON_MALFORMED", "unpaired Unicode surrogate");
                    } else {
                        let scalar = char::from_u32(high as u32).expect("non-surrogate code point");
                        decoded_bytes += scalar.len_utf8();
                        position += 6;
                    }
                }
                _ => return reject("E_JSON_MALFORMED", "malformed JSON string escape"),
            }
        }
        if decoded_bytes > STRING_BYTES_LIMIT {
            return reject("E_LIMIT_STRING", "string exceeds 4 KiB");
        }
    }
    Ok(())
}

fn hex_quad(encoded: Option<&[u8]>) -> Result<u16, ThemeError> {
    let Some(encoded) = encoded.filter(|encoded| encoded.len() == 4) else {
        return reject("E_JSON_MALFORMED", "malformed Unicode escape");
    };
    let mut value = 0u16;
    for byte in encoded {
        let digit = match byte {
            b'0'..=b'9' => byte - b'0',
            b'a'..=b'f' => byte - b'a' + 10,
            b'A'..=b'F' => byte - b'A' + 10,
            _ => return reject("E_JSON_MALFORMED", "malformed Unicode escape"),
        };
        value = value * 16 + digit as u16;
    }
    Ok(value)
}

fn is_token_layer(path: &[String]) -> bool {
    path.len() == 3
        && path[0] == "variants"
        && matches!(path[1].as_str(), "light" | "dark" | "high-contrast")
        && matches!(path[2].as_str(), "primitives" | "semantic" | "components")
}

fn is_asset_items(path: &[String]) -> bool {
    path.len() == 4
        && path[0] == "variants"
        && matches!(path[1].as_str(), "light" | "dark" | "high-contrast")
        && path[2] == "assets"
        && path[3] == "items"
}

fn is_decoded_bytes(path: &[String]) -> bool {
    path.len() == 6
        && path[0] == "variants"
        && matches!(path[1].as_str(), "light" | "dark" | "high-contrast")
        && path[2] == "assets"
        && path[3] == "items"
        && path[5] == "decoded_bytes"
}
