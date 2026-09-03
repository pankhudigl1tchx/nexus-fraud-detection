export async function analyzeLoan(loanData) {
  try {
    const response = await fetch("http://localhost:8000/analyze-loan", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(loanData),
    });

    if (!response.ok) {
      throw new Error(`Server returned status ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Error analyzing loan:", error);
    throw error;
  }
}