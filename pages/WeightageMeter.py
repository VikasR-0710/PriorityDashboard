def get_weightage_summary(filtered_df):
    """Return the values formerly displayed by the Weightage Meter."""
    score_column = "Case Score Display" if "Case Score Display" in filtered_df.columns else "Case Score"
    total_score = float(filtered_df[score_column].sum())
    owners = int(filtered_df["Case Owner"].nunique())
    return {
        "total_score": total_score,
        "max_score": max(total_score + 50, 100),
        "selected_regions": int(filtered_df["Region"].nunique()),
        "selected_owners": owners,
        "owner": str(filtered_df["Case Owner"].iloc[0]) if owners == 1 and not filtered_df.empty else None,
    }
