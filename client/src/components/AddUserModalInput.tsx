import React from "react";

interface AddUserModalInputProps {
    placeholder: string;
    handleFormChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    value?: string;
    error?: boolean
}

export const AddUserModalInput = ({placeholder, handleFormChange, value = '', error}: AddUserModalInputProps) => {

    return (
        <input
            onChange={handleFormChange}
            type="text" className={`${error ? 'modal_input_error' : 'modal_input'}`}
            value={value}
            placeholder={placeholder}
            autoComplete='off'
        />
    );
};
