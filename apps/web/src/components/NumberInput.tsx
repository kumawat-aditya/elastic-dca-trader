import React, { useState, useEffect } from "react";

export function NumberInput({
  value,
  onChange,
  min = 0,
  step = "any",
  isInteger = false,
  className = "",
  disabled = false,
}: {
  value: number | string | null;
  onChange: (val: number | null) => void;
  min?: number;
  step?: string;
  isInteger?: boolean;
  className?: string;
  disabled?: boolean;
}) {
  const [localVal, setLocalVal] = useState<string>(
    value === null ? "" : value.toString(),
  );

  useEffect(() => {
    const strVal = value === null ? "" : value.toString();
    if (localVal !== strVal && parseFloat(localVal) !== parseFloat(strVal)) {
      setLocalVal(strVal);
    }
  }, [value]);

  const handleBlur = () => {
    if (localVal.trim() === "") {
      onChange(null);
      return;
    }
    let parsed = isInteger ? parseInt(localVal, 10) : parseFloat(localVal);
    if (isNaN(parsed)) {
      onChange(null);
      setLocalVal("");
      return;
    }
    if (parsed < min) parsed = min;
    setLocalVal(parsed.toString());
    onChange(parsed);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = e.target.value;
    setLocalVal(newVal);

    if (newVal.trim() === "") {
      onChange(null);
      return;
    }

    let parsed = isInteger ? parseInt(newVal, 10) : parseFloat(newVal);
    if (!isNaN(parsed)) {
      onChange(parsed);
    }
  };

  return (
    <input
      type="number"
      min={min}
      step={step}
      value={localVal}
      onChange={handleChange}
      onBlur={handleBlur}
      className={className}
      disabled={disabled}
    />
  );
}
