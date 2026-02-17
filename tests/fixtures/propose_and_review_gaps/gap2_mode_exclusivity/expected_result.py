"""Sample module for testing mode exclusivity."""


def new_function(x: int, y: int) -> int:
    """New function implementation.
    
    This function adds two numbers together.
    
    Args:
        x: First number
        y: Second number
        
    Returns:
        Sum of x and y
    """
    return x + y


def helper_function():
    """Helper that calls new_function."""
    result = new_function(1, 2)
    return result


# Usage example
if __name__ == "__main__":
    print(new_function(5, 3))