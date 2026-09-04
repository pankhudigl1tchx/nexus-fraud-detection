const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://nexus-fraud-detection.onrender.com";

export async function analyzeLoan(loanData: any) {
  try {
    const response = await fetch(`${API_BASE_URL}/analyze-loan`, {
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