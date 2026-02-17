"""Sample module for testing mode exclusivity."""


def old_function(x: int, y: int) -> int:
    """Old function implementation.
    
    This function adds two numbers together.
    
    Args:
        x: First number
        y: Second number
        
    Returns:
        Sum of x and y
    """
    return x + y


def helper_function():
    """Helper that calls old_function."""
    result = old_function(1, 2)
    return result


# Usage example
if __name__ == "__main__":
    print(old_function(5, 3))